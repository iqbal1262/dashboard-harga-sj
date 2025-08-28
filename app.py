import streamlit as st
import pandas as pd
from rapidfuzz import fuzz, process
import numpy as np
import re
from collections import defaultdict
from datasketch import MinHash, MinHashLSH
import difflib
import requests
from io import StringIO
import chardet

# --- Konfigurasi Halaman Streamlit ---
st.set_page_config(layout="wide", page_title="Dashboard Konsistensi Nama Barang")

st.title("📊 Dashboard Konsistensi Nama Barang")
st.write("Aplikasi ini membantu dalam menemukan nama barang yang mirip dari beberapa kategori di Google Sheets untuk memeriksa konsistensi harga.")

# --- Informasi Spreadsheet (Hardcoded) ---
SPREADSHEET_ID = "1-dKGrGEbxG_xCEIl9j4t16m9f3vA-sTd"
# Kamus untuk memetakan nama kategori ke GID sheet masing-masing
SHEET_GIDS = {
    "Air Tawar": 1009147309,
    "Cat": 1737557785,
    "Consumables": 2051663873,
    "Deck": 1661742034,
    "Inventaris Kapal": 98003251,
    "LPG dan Minyak": 842660792,
    "Mesin": 295793469,
    "Oksigen": 1971371121,
    "Oli": 152023423
}
CATEGORIES = list(SHEET_GIDS.keys())

# --- Fungsi untuk memuat data dari Google Sheets publik ---
# Menggunakan cache agar tidak perlu memuat ulang data setiap kali ada interaksi
@st.cache_data(ttl=600) # Cache data selama 10 menit
def load_public_data(selected_categories):
    all_dfs = []
    base_export = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv"
    base_pub = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/pub?gid={{}}&single=true&output=csv"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for category in selected_categories:
        gid = SHEET_GIDS.get(category)
        if gid is None:
            continue

        urls = [
            f"{base_export}&gid={gid}",
            base_pub.format(gid)
        ]

        loaded = False
        for url in urls:
            try:
                r = requests.get(url, headers=headers, timeout=30)
            except Exception:
                continue

            if r.status_code != 200:
                continue

            snippet_bytes = r.content[:2000]
            # if response contains HTML, skip this url
            try:
                if b'<!doctype html' in snippet_bytes.lower() or b'<html' in snippet_bytes.lower():
                    continue
            except Exception:
                pass

            # try multiple encodings and header options
            guess = chardet.detect(r.content) or {}
            encodings_to_try = ['utf-8-sig', 'utf-8', guess.get('encoding'), 'latin1']
            df = None
            for enc in encodings_to_try:
                if not enc:
                    continue
                try:
                    text = r.content.decode(enc, errors='replace')
                except Exception:
                    continue

                first_line = text.splitlines()[0] if text.splitlines() else ""
                sep = None
                if first_line.startswith("sep="):
                    sep = first_line.split("=", 1)[1].strip()

                for header in [0, 1, None]:
                    try:
                        sio = StringIO(text)
                        if sep:
                            tmp = pd.read_csv(sio, sep=sep, header=header, engine='python')
                        else:
                            tmp = pd.read_csv(sio, header=header, engine='python')
                        if tmp.shape[1] >= 1:
                            df = tmp
                            break
                    except Exception:
                        continue

                if df is not None:
                    break

            if df is not None:
                all_dfs.append(df)
                loaded = True
                break  # move to next category

        # if not loaded, silently skip this category

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    return combined

# --- Fungsi untuk menyorot perbedaan teks ---
def highlight_diff(text1, text2):
    """
    Membandingkan dua teks dan mengembalikannya dengan perbedaan yang disorot menggunakan HTML.
    """
    sm = difflib.SequenceMatcher(None, str(text1), str(text2))
    output1, output2 = "", ""
    style_del = 'style="background-color: #ffcdd2; padding: 2px; border-radius: 3px;"' # Merah muda
    style_ins = 'style="background-color: #c8e6c9; padding: 2px; border-radius: 3px;"' # Hijau muda
    
    for opcode, i1, i2, j1, j2 in sm.get_opcodes():
        if opcode == 'equal':
            output1 += text1[i1:i2]
            output2 += text2[j1:j2]
        elif opcode == 'replace':
            output1 += f'<span {style_del}>{text1[i1:i2]}</span>'
            output2 += f'<span {style_ins}>{text2[j1:j2]}</span>'
        elif opcode == 'delete':
            output1 += f'<span {style_del}>{text1[i1:i2]}</span>'
        elif opcode == 'insert':
            output2 += f'<span {style_ins}>{text2[j1:j2]}</span>'
            
    return output1, output2

# --- Fungsi untuk menjalankan analisis MinHash LSH pada sebuah DataFrame ---
def run_lsh_analysis(df_group, threshold, num_perm=128):
    if len(df_group) < 2:
        return []

    df_group = df_group.reset_index(drop=True)
    
    minhashes = []
    for i in range(len(df_group)):
        name = df_group.loc[i, 'NAMABRG']
        m = MinHash(num_perm=num_perm)
        for d in [name[j:j+3] for j in range(len(name)-2)]:
            m.update(d.encode('utf8'))
        minhashes.append(m)

    lsh = MinHashLSH(threshold=0.6, num_perm=num_perm)
    for i, m in enumerate(minhashes):
        lsh.insert(f"item_{i}", m)

    candidate_pairs = set()
    for i, m in enumerate(minhashes):
        result_keys = lsh.query(m)
        for key in result_keys:
            j = int(key.split('_')[1])
            if i < j:
                candidate_pairs.add((i, j))
    
    group_pairs = []
    names = df_group['NAMABRG'].tolist()
    for i, j in candidate_pairs:
        score = fuzz.ratio(names[i], names[j])
        if score >= threshold:
            group_pairs.append({
                "NAMABRG_A": names[i],
                "KODE_A": df_group.loc[i, "KODEBARANG"],
                "HARGA_A": df_group.loc[i, "HARGA"],
                "SATUAN_A": df_group.loc[i, "SATUAN"],
                "NAMABRG_B": names[j],
                "KODE_B": df_group.loc[j, "KODEBARANG"],
                "HARGA_B": df_group.loc[j, "HARGA"],
                "SATUAN_B": df_group.loc[j, "SATUAN"],
                "SCORE": score
            })
    return group_pairs

# --- Inisialisasi Session State ---
if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None

# --- Input dari Pengguna di Sidebar ---
st.sidebar.header("⚙️ Pengaturan")
selected_categories = st.sidebar.multiselect(
    "Pilih kategori barang untuk dianalisis",
    CATEGORIES,
    help="Anda bisa memilih lebih dari satu kategori."
)

st.sidebar.header("🔍 Filter Analisis")

# --- PEMBARUAN: Mengganti nama mode analisis ---
analysis_mode = st.sidebar.radio(
    "Pilih Mode Analisis:",
    ('Filter Ketat', 'Filter Cepat'),
    index=0, # Default ke Filter Ketat
    help="**Filter Ketat:** Akurasi tertinggi, waktu proses lebih lama. **Filter Cepat:** Performa lebih cepat, cocok untuk analisis awal."
)

threshold = st.sidebar.slider("Filter Kemiripan Nama (%)", 70, 100, 85)

# --- Tombol untuk Memulai Proses ---
if st.sidebar.button("Proses Data"):
    if not selected_categories:
        st.warning("Mohon pilih setidaknya satu kategori untuk diproses.")
    else:
        with st.spinner('Memuat dan memproses data...'):
            df = load_public_data(selected_categories)

        if df is not None and not df.empty:
            st.success(f"Data berhasil dimuat. Ditemukan {len(df)} baris dari kategori yang dipilih.")
            
            required_columns = ["NAMABRG", "KODEBARANG", "HARGA", "SATUAN"]
            if not all(col in df.columns for col in required_columns):
                st.error(f"Data tidak memiliki kolom yang dibutuhkan: {', '.join(required_columns)}. Silakan periksa nama kolom di Google Sheet.")
                st.session_state.analysis_result = None
            else:
                df.dropna(subset=["NAMABRG"], inplace=True)
                df['NAMABRG'] = df['NAMABRG'].astype(str)
                df['HARGA'] = pd.to_numeric(df['HARGA'], errors='coerce').fillna(0)
                df['SATUAN'] = df['SATUAN'].fillna('TIDAK ADA').astype(str)
                
                initial_rows = len(df)
                df.drop_duplicates(subset=['NAMABRG', 'HARGA'], keep='first', inplace=True)
                final_rows = len(df)
                st.info(f"Menghapus {initial_rows - final_rows} baris duplikat (nama & harga sama). Data untuk analisis: {final_rows} baris.")

                df = df.reset_index(drop=True)
                
                # Menentukan parameter berdasarkan mode yang dipilih
                num_permutations = 128 if analysis_mode == 'Filter Ketat' else 64
                
                all_pairs = []
                unique_units = df['SATUAN'].unique()
                progress_bar = st.progress(0, text=f"Menganalisis per kelompok satuan (Mode: {analysis_mode})...")
                for i, unit in enumerate(unique_units):
                    progress_bar.progress((i + 1) / len(unique_units), text=f"Menganalisis satuan: {unit}...")
                    df_group = df[df['SATUAN'] == unit]
                    group_pairs = run_lsh_analysis(df_group, threshold, num_perm=num_permutations)
                    all_pairs.extend(group_pairs)
                progress_bar.empty()

                if all_pairs:
                    result = pd.DataFrame(all_pairs)
                    denominator = result[['HARGA_A', 'HARGA_B']].max(axis=1)
                    result['PERBEDAAN_HARGA (%)'] = np.where(denominator > 0, (result['HARGA_A'] - result['HARGA_B']).abs() / denominator * 100, 0)
                    result = result.sort_values(by="SCORE", ascending=False).reset_index(drop=True)
                    st.session_state.analysis_result = result
                else:
                    st.session_state.analysis_result = pd.DataFrame()
        else:
            st.info("Tidak ada data yang ditemukan di kategori yang dipilih atau terjadi kesalahan saat memuat.")
            st.session_state.analysis_result = None

# --- Tampilkan Hasil dari Session State ---
if st.session_state.analysis_result is not None:
    if not st.session_state.analysis_result.empty:
        result = st.session_state.analysis_result
        st.markdown("---")
        st.header("🔍 Hasil Analisis")
        
        # 1. Tampilkan Tabel Hasil Lengkap Terlebih Dahulu
        st.subheader("📋 Tabel Hasil Lengkap")
        st.write(f"Menampilkan **{len(result)}** total pasangan yang ditemukan.")
        
        df_for_display = result[[
            "SCORE", "PERBEDAAN_HARGA (%)", "NAMABRG_A", "HARGA_A", "SATUAN_A", "KODE_A",
            "NAMABRG_B", "HARGA_B", "SATUAN_B", "KODE_B"
        ]]

        styled_df = df_for_display.style.format({
            'HARGA_A': "Rp {:,.0f}",
            'HARGA_B': "Rp {:,.0f}",
            'SCORE': '{:.2f}',
            'PERBEDAAN_HARGA (%)': '{:.2f}%'
        }).set_properties(
            **{'background-color': '#e8f5e9'},  # Hijau Muda
            subset=['NAMABRG_A', 'NAMABRG_B']
        ).set_properties(
            **{'background-color': "#e3f2fd"},  # Biru Muda
            subset=['HARGA_A', 'HARGA_B']
        )
        
        st.dataframe(styled_df)

        st.markdown("---")

        # 2. Tampilkan Fitur Perbandingan Detail Setelah Tabel
        st.subheader("🔬 Perbandingan Detail")

        if not result.empty:
            unique_names = pd.concat([result['NAMABRG_A'], result['NAMABRG_B']]).unique()
            primary_item = st.selectbox("Pilih barang utama untuk melihat semua pasangannya yang mirip:", unique_names)

            if primary_item:
                related_pairs = result[
                    (result['NAMABRG_A'] == primary_item) | 
                    (result['NAMABRG_B'] == primary_item)
                ]

                st.write(f"Menampilkan {len(related_pairs)} pasangan yang mirip dengan **{primary_item}**:")

                for _, row in related_pairs.iterrows():
                    if row['NAMABRG_A'] == primary_item:
                        item_a_name, item_a_price, item_a_unit, item_a_code = row['NAMABRG_A'], row['HARGA_A'], row['SATUAN_A'], row['KODE_A']
                        item_b_name, item_b_price, item_b_unit, item_b_code = row['NAMABRG_B'], row['HARGA_B'], row['SATUAN_B'], row['KODE_B']
                    else:
                        item_a_name, item_a_price, item_a_unit, item_a_code = row['NAMABRG_B'], row['HARGA_B'], row['SATUAN_B'], row['KODE_B']
                        item_b_name, item_b_price, item_b_unit, item_b_code = row['NAMABRG_A'], row['HARGA_A'], row['SATUAN_A'], row['KODE_A']

                    highlighted_a, highlighted_b = highlight_diff(item_a_name, item_b_name)
                    
                    st.markdown("---")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("#### Barang Utama")
                        st.markdown(f"**Nama:** {highlighted_a}", unsafe_allow_html=True)
                        st.markdown(f"**Harga:** Rp {int(item_a_price):,}".replace(',', '.'))
                        st.markdown(f"**Satuan:** {item_a_unit}")
                        st.markdown(f"**Kode:** {item_a_code}")
                    
                    with col2:
                        st.markdown("#### Pasangan Mirip")
                        st.markdown(f"**Nama:** {highlighted_b}", unsafe_allow_html=True)
                        st.markdown(f"**Harga:** Rp {int(item_b_price):,}".replace(',', '.'))
                        st.markdown(f"**Satuan:** {item_b_unit}")
                        st.markdown(f"**Kode:** {item_b_code}")
        else:
            st.warning("Tidak ada hasil yang cocok dengan pencarian Anda untuk dibandingkan.")

    else:
        st.info(f"Tidak ditemukan pasangan nama barang yang mirip dengan skor di atas {threshold}.")
else:
    st.info("Silakan pilih kategori dan klik 'Proses Data' untuk memulai analisis.")
