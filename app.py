import streamlit as st
import pandas as pd
import numpy as np
import difflib
import requests
from io import StringIO

# --- Konfigurasi Halaman Streamlit ---
st.set_page_config(layout="wide", page_title="Dashboard Hasil Analisis Harga")

st.title("📊 Dashboard Penampil Database Konsistensi Harga")
st.write("Aplikasi ini menampilkan hasil analisis kemiripan barang dari database yang sudah diproses.")

# --- Informasi Spreadsheet (Database) ---
SPREADSHEET_ID_DB = "1_CXkB0wkdj3MC7YdewWdYDxns4iplsXF"
SPREADSHEET_ID_SJ = "1NcsaPVBVqlg6fcKHS2XYxkzyPNGiAaYc"

# --- Fungsi untuk memuat data dari Google Sheets publik ---
@st.cache_data(ttl=3600) # Cache data selama 1 jam
def load_database(spreadsheet_id, gid):
    """
    Fungsi generik untuk membaca database dari sheet publik Google Sheets.
    """
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
    try:
        df = pd.read_csv(url)
        # --- PERBAIKAN: Menghapus kolom 'Unnamed: 0' jika ada ---
        if 'Unnamed: 0' in df.columns:
            df = df.drop(columns=['Unnamed: 0'])
        return df
    except Exception as e:
        st.error(f"Gagal memuat data dari Google Sheet (ID: {spreadsheet_id}). Pastikan link publik dan formatnya benar. Error: {e}")
        return pd.DataFrame()

# --- Fungsi untuk menyorot perbedaan teks ---
def highlight_diff(text1, text2):
    sm = difflib.SequenceMatcher(None, str(text1), str(text2))
    output1, output2 = "", ""
    style_del = 'style="background-color: #ffcdd2; padding: 2px; border-radius: 3px;"'
    style_ins = 'style="background-color: #c8e6c9; padding: 2px; border-radius: 3px;"'
    
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

# --- Inisialisasi Session State ---
if 'filtered_df' not in st.session_state:
    st.session_state.filtered_df = None

# --- Memuat Database ---
db_df = load_database(SPREADSHEET_ID_DB, gid="1872490756")
if not db_df.empty:
    # Membersihkan nama kolom untuk kemudahan akses
    db_df.columns = (
        db_df.columns.str.strip()
        .str.replace(' (%)', '_PERSEN', regex=False)
        .str.replace(' ', '_')
    )
    db_df['SCORE'] = pd.to_numeric(db_df['SCORE'], errors='coerce')
    db_df['SELISIH_HARGA_PERSEN'] = pd.to_numeric(db_df['SELISIH_HARGA_PERSEN'], errors='coerce')
    db_df.dropna(subset=['SCORE', 'SELISIH_HARGA_PERSEN'], inplace=True)

# --- Sidebar Filters ---
st.sidebar.header("🔍 Filter Data")
if not db_df.empty:
    score_filter_option = st.sidebar.selectbox(
        "Filter Kemiripan SCORE:",
        ('Tampilkan Semua (>= 90%)', 'Hampir Identik (>= 95%)', 'Sangat Mirip (Skor 100)')
    )

    all_categories = sorted(pd.concat([db_df['KATEGORI_A'], db_df['KATEGORI_B']]).dropna().unique())
    selected_categories = st.sidebar.multiselect(
        "Filter berdasarkan Kategori",
        options=all_categories,
        default=[] # Default ke tidak ada kategori yang dipilih
    )

    # --- Tombol START untuk memulai filter ---
    if st.sidebar.button("START"):
        if not selected_categories:
            st.sidebar.warning("Mohon pilih setidaknya satu kategori.")
            st.session_state.filtered_df = pd.DataFrame(columns=db_df.columns) # Simpan dataframe kosong
        else:
            if score_filter_option == 'Tampilkan Semua (>= 90%)':
                score_condition = (db_df['SCORE'] >= 90)
            elif score_filter_option == 'Hampir Identik (>= 95%)':
                score_condition = (db_df['SCORE'] >= 95)
            else: # Sangat Mirip (Skor 100)
                score_condition = (db_df['SCORE'] == 100)

            if len(selected_categories) == 1:
                category_filter = (db_df['KATEGORI_A'] == selected_categories[0]) & (db_df['KATEGORI_B'] == selected_categories[0])
            else:
                category_filter = (db_df['KATEGORI_A'].isin(selected_categories)) & (db_df['KATEGORI_B'].isin(selected_categories))

            filtered_df = db_df[
                score_condition &
                category_filter
            ]
            
            filtered_df = filtered_df.sort_values(by="SCORE", ascending=False).reset_index(drop=True)
            st.session_state.filtered_df = filtered_df # Simpan hasil filter ke session state

# --- Menampilkan hasil HANYA jika sudah difilter ---
if st.session_state.filtered_df is not None:
    filtered_df = st.session_state.filtered_df
    st.markdown("---")
    st.header("📋 Hasil Filter")

    if not filtered_df.empty:
        st.write(f"Menampilkan **100 baris teratas** dari **{len(filtered_df)}** total pasangan yang cocok dengan filter.")
        display_df_limited = filtered_df.head(100)
        
        display_df = display_df_limited[[
            "SCORE", "SELISIH_HARGA_PERSEN", "BARANG_A", "HARGA_A", "SATUAN", "KODE_A", "KATEGORI_A",
            "BARANG_B", "HARGA_B", "KODE_B", "KATEGORI_B"
        ]]

        styled_df = display_df.style.format({
            'HARGA_A': "Rp {:,.0f}",
            'HARGA_B': "Rp {:,.0f}",
            'SCORE': '{:.2f}',
            'SELISIH_HARGA_PERSEN': '{:.2f}%'
        }).set_properties(
            **{'background-color': '#e8f5e9'},
            subset=["BARANG_A", "BARANG_B"] # --- PERBAIKAN: Menggunakan petik dua ---
        ).set_properties(
            **{'background-color': "#e3f2fd"},
            subset=["HARGA_A", "HARGA_B"] # --- PERBAIKAN: Menggunakan petik dua ---
        )
        
        st.dataframe(styled_df)

        st.markdown("---")

        st.header("🔬 Perbandingan Detail")
        unique_names = pd.concat([filtered_df['BARANG_A'], filtered_df['BARANG_B']]).unique()
        primary_item = st.selectbox("Pilih barang utama untuk dianalisis:", unique_names)

        if primary_item:
            tab1, tab2 = st.tabs(["Perbandingan Side-by-Side", "Tinjau Data SJ"])

            with tab1:
                related_pairs = filtered_df[
                    (filtered_df['BARANG_A'] == primary_item) | 
                    (filtered_df['BARANG_B'] == primary_item)
                ]

                st.write(f"Menampilkan {len(related_pairs)} pasangan yang mirip dengan **{primary_item}**:")

                for _, row in related_pairs.iterrows():
                    if row['BARANG_A'] == primary_item:
                        item_a_name, item_a_price, item_a_unit, item_a_code, item_a_cat = row['BARANG_A'], row['HARGA_A'], row['SATUAN'], row['KODE_A'], row['KATEGORI_A']
                        item_b_name, item_b_price, item_b_unit, item_b_code, item_b_cat = row['BARANG_B'], row['HARGA_B'], row['SATUAN'], row['KODE_B'], row['KATEGORI_B']
                    else:
                        item_a_name, item_a_price, item_a_unit, item_a_code, item_a_cat = row['BARANG_B'], row['HARGA_B'], row['SATUAN'], row['KODE_B'], row['KATEGORI_B']
                        item_b_name, item_b_price, item_b_unit, item_b_code, item_b_cat = row['BARANG_A'], row['HARGA_A'], row['SATUAN'], row['KODE_A'], row['KATEGORI_A']

                    highlighted_a, highlighted_b = highlight_diff(item_a_name, item_b_name)
                    
                    st.markdown("---")
                    col1_tab1, col2_tab1 = st.columns(2)
                    with col1_tab1:
                        st.markdown("#### Barang Utama")
                        st.markdown(f"**Nama:** {highlighted_a}", unsafe_allow_html=True)
                        st.markdown(f"**Harga:** Rp {int(item_a_price):,}".replace(',', '.'))
                        st.markdown(f"**Satuan:** {item_a_unit}")
                        st.markdown(f"**Kode:** {item_a_code}")
                        st.markdown(f"**Kategori:** {item_a_cat}")
                    
                    with col2_tab1:
                        st.markdown("#### Pasangan Mirip")
                        st.markdown(f"**Nama:** {highlighted_b}", unsafe_allow_html=True)
                        st.markdown(f"**Harga:** Rp {int(item_b_price):,}".replace(',', '.'))
                        st.markdown(f"**Satuan:** {item_b_unit}")
                        st.markdown(f"**Kode:** {item_b_code}")
                        st.markdown(f"**Kategori:** {item_b_cat}")
            
            with tab2:
                st.subheader(f"Mencari riwayat pembelian untuk: {primary_item}")
                with st.spinner("Memuat data riwayat pembelian..."):
                    sj_df = load_database(SPREADSHEET_ID_SJ, gid="1615588726") 
                
                if not sj_df.empty:
                    if 'NAMABRG' in sj_df.columns:
                        sj_filtered = sj_df[sj_df['NAMABRG'].str.contains(primary_item, case=False, na=False)]
                        
                        if not sj_filtered.empty:
                            st.write(f"Ditemukan {len(sj_filtered)} riwayat pembelian:")
                            st.dataframe(sj_filtered)
                        else:
                            st.warning(f"Tidak ditemukan riwayat pembelian untuk '{primary_item}' di Data SJ.")
                    else:
                        st.error("Kolom 'NAMABRG' tidak ditemukan di spreadsheet Data SJ.")
                else:
                    st.error("Gagal memuat Data SJ.")

    else:
        st.warning("Tidak ada data yang cocok dengan filter Anda.")
else:
    st.info("Pilih filter di sidebar dan klik 'START' untuk memulai.")

if db_df.empty:
    st.error("Database utama tidak dapat dimuat. Aplikasi tidak dapat berjalan.")
