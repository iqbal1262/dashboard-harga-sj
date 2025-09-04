import streamlit as st
import pandas as pd
import numpy as np
import difflib
from rapidfuzz import process, fuzz
import re
import io
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account


# --- Konfigurasi Halaman Streamlit ---
st.set_page_config(layout="wide", page_title="Dashboard Hasil Analisis Harga")

st.title("📊 Dashboard Penampil Database Konsistensi Harga")
st.write("Aplikasi ini menampilkan hasil analisis kemiripan barang dari database yang sudah diproses.")


SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]  # read-only lebih aman
CREDS = service_account.Credentials.from_service_account_info(
    dict(st.secrets["gcp_service_account"]), scopes=SCOPES
)
DRIVE = build("drive", "v3", credentials=CREDS)

# --- Informasi File di Google Drive ---
FILE_ID_DB = "1_CXkB0wkdj3MC7YdewWdYDxns4iplsXF"  # Database kemiripan (xlsx atau Google Sheet)
FILE_ID_SJ = "1NcsaPVBVqlg6fcKHS2XYxkzyPNGiAaYc"  # Data SJ (xlsx atau Google Sheet)


# Nama sheet dalam file (opsional). Jika None -> sheet pertama
SHEET_NAME_DB: Optional[str] = None  # mis. "Database"
SHEET_NAME_SJ: Optional[str] = None  # mis. "Sheet1"

# --- Loader: dukung Excel privat & Google Spreadsheet privat ---
@st.cache_data(ttl=3600)
def load_excel_from_drive(file_id: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
    """Download file Excel privat dari Google Drive via Service Account dan load ke DataFrame.
    - Jika file adalah Google Spreadsheet, akan di-export ke XLSX dulu.
    - Pastikan file di-share ke client_email Service Account (Viewer/Editor).
    """
    try:
        meta = DRIVE.files().get(fileId=file_id, fields="name,mimeType").execute()
        mime = meta.get("mimeType", "")
        name = meta.get("name", file_id)

        # Tentukan request download
        if mime == "application/vnd.google-apps.spreadsheet":
            # Export Google Sheet menjadi XLSX
            request = DRIVE.files().export_media(
                fileId=file_id,
                mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        elif mime in ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel"):
            # XLSX/XLS asli
            request = DRIVE.files().get_media(fileId=file_id)
        else:
            st.warning(f"File '{name}' (mimeType={mime}) bukan Excel/Spreadsheet. Pastikan formatnya XLSX atau Google Sheet.")
            request = DRIVE.files().get_media(fileId=file_id)  # coba saja download biner

        # Download konten ke BytesIO
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)

        # Baca excel (bisa multi-sheet)
        df = pd.read_excel(fh, sheet_name=sheet_name, engine="openpyxl")
        if isinstance(df, dict):  # kalau multi-sheet dan sheet_name=None
            first_key = list(df.keys())[0]
            df = df[first_key]

        # --- PERBAIKAN: Membersihkan nama kolom secara otomatis ---
        df.columns = df.columns.str.strip()

        # Bersihkan kolom index sisa export jika ada
        if "Unnamed: 0" in df.columns:
            df = df.drop(columns=["Unnamed: 0"])
            
        # --- PERUBAHAN: Selalu pastikan kolom harga dan jumlah adalah numerik ---
        currency_cols = ['HARGARATA', 'TOTALHARGA']
        for col in currency_cols:
            if col in df.columns:
                cleaned_val = df[col].astype(str).str.replace(r'[^\d.]', '', regex=True)
                df[col] = pd.to_numeric(cleaned_val, errors='coerce')
        
        # --- PERBAIKAN: Mengatasi error casting float ke int ---
        int_cols = ['JUMLAH', 'JMLDISETUJUI', 'JML_DITERIMA']
        for col in int_cols:
            if col in df.columns:
                # Mengisi NaN dengan 0 dan membulatkan sebelum mengubah ke integer
                numeric_vals = pd.to_numeric(df[col], errors='coerce').fillna(0)
                df[col] = numeric_vals.round().astype(int)

        if 'SJ_CREATED_ON' in df.columns:
            df['SJ_CREATED_ON'] = pd.to_datetime(df['SJ_CREATED_ON'], errors='coerce')
            
        return df
    except Exception as e:
        st.error(f"Gagal memuat Excel dari Drive (fileId={file_id}): {e}")
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
if 'new_item_results' not in st.session_state:
    st.session_state.new_item_results = None

# --- Memuat Database (Excel/Sheet privat) ---
db_df = load_excel_from_drive(FILE_ID_DB, sheet_name=SHEET_NAME_DB)

if not db_df.empty:
    # Membersihkan nama kolom untuk kemudahan akses
    db_df.columns = (
        db_df.columns.astype(str).str.strip()
        .str.replace(' (%)', '_PERSEN', regex=False)
        .str.replace(' ', '_')
    )
    # Pastikan kolom numerik dalam tipe numeric
    if 'SCORE' in db_df.columns:
        db_df['SCORE'] = pd.to_numeric(db_df['SCORE'], errors='coerce')
    if 'SELISIH_HARGA_PERSEN' in db_df.columns:
        db_df['SELISIH_HARGA_PERSEN'] = pd.to_numeric(db_df['SELISIH_HARGA_PERSEN'], errors='coerce')
    # Buang baris tanpa nilai numerik penting
    drop_cols = [c for c in ['SCORE', 'SELISIH_HARGA_PERSEN'] if c in db_df.columns]
    if drop_cols:
        db_df.dropna(subset=drop_cols, inplace=True)
else:
    st.error("Database utama tidak dapat dimuat dari Drive. Aplikasi tidak dapat berjalan.")

# --- Sidebar Filters ---
st.sidebar.header("🔍 Filter Data")
if not db_df.empty:
    score_filter_option = st.sidebar.selectbox(
        "Filter Kemiripan SCORE:",
        ('Tampilkan Semua (>= 90%)', 'Hampir Identik (>= 95%)', 'Sangat Mirip (Skor 100)')
    )

    # KATEGORI_A/B bisa tidak ada jika struktur berbeda — handle aman
    if all(col in db_df.columns for col in ['KATEGORI_A', 'KATEGORI_B']):
        all_categories = sorted(pd.concat([db_df['KATEGORI_A'], db_df['KATEGORI_B']]).dropna().unique())
    else:
        all_categories = []

    selected_categories = st.sidebar.multiselect(
        "Filter berdasarkan Kategori",
        options=all_categories,
        default=[]
    )

    if st.sidebar.button("START"):
        if not selected_categories:
            st.sidebar.warning("Mohon pilih setidaknya satu kategori.")
            st.session_state.filtered_df = pd.DataFrame(columns=db_df.columns)
        else:
            if score_filter_option == 'Tampilkan Semua (>= 90%)':
                score_condition = (db_df['SCORE'] >= 90)
            elif score_filter_option == 'Hampir Identik (>= 95%)':
                score_condition = (db_df['SCORE'] >= 95)
            else:  # Sangat Mirip (Skor 100)
                score_condition = (db_df['SCORE'] == 100)

            if len(selected_categories) == 1:
                category_filter = (db_df['KATEGORI_A'] == selected_categories[0]) & (db_df['KATEGORI_B'] == selected_categories[0])
            else:
                category_filter = (db_df['KATEGORI_A'].isin(selected_categories)) & (db_df['KATEGORI_B'].isin(selected_categories))

            filtered_df = db_df[
                score_condition &
                category_filter
            ]

            # Default sort order
            filtered_df = filtered_df.sort_values(by="SCORE", ascending=False).reset_index(drop=True)
            st.session_state.filtered_df = filtered_df

# --- Fitur Cek Barang Baru ---
st.sidebar.markdown("---")
st.sidebar.header("🧪 Cek Histori Nama Barang")
# --- PEMBARUAN: Menambahkan st.info ---
# st.sidebar.caption("Gunakan menu ini untuk memeriksa apakah suatu nama barang sudah ada di histori data SJ untuk menjaga konsistensi pencatatan.")
with st.sidebar.expander("ℹ️ Tentang Fitur Ini"):
    st.write("Gunakan menu ini untuk memeriksa apakah suatu nama barang sudah ada di histori data SJ untuk menjaga konsistensi pencatatan.")
# st.sidebar.info("Gunakan menu ini untuk memeriksa apakah suatu nama barang sudah ada di histori data SJ untuk menjaga konsistensi pencatatan.")
new_item_name = st.sidebar.text_input("Masukkan nama barang untuk dicek:")
if st.sidebar.button("Cek Kemiripan"):
    if not new_item_name:
        st.sidebar.warning("Nama barang tidak boleh kosong.")
    else:
        with st.spinner("Memuat data master SJ dan mencari kemiripan..."):
            sj_df = load_excel_from_drive(FILE_ID_SJ, sheet_name=SHEET_NAME_SJ)

            if not sj_df.empty and 'NAMABRG' in sj_df.columns and 'SJ_CREATED_ON' in sj_df.columns:
                
                sj_df_sorted = sj_df.sort_values(by='SJ_CREATED_ON', ascending=False)
                master_list_df = sj_df_sorted.groupby(['NAMABRG', 'KODEBARANG', 'SATUAN']).agg(
                    HARGARATA=('HARGARATA', 'first'),
                    KATEGORI=('KATEGORI', 'first'),
                    Permintaan_Terakhir=('SJ_CREATED_ON', 'max'),
                    Permintaan_Awal=('SJ_CREATED_ON', 'min')
                ).reset_index()

                choices = master_list_df['NAMABRG'].tolist()
                query_name = new_item_name.upper()

                initial_matches = process.extract(query_name, choices, scorer=fuzz.ratio, limit=10, score_cutoff=50)

                match_results = []
                processed_items = set()

                initial_names = {match[0] for match in initial_matches}
                names_to_process_queue = list(initial_names)

                while names_to_process_queue:
                    current_name = names_to_process_queue.pop(0)

                    variations = master_list_df[master_list_df['NAMABRG'] == current_name]

                    for _, detail_row in variations.iterrows():
                        item_tuple = (detail_row['NAMABRG'], detail_row['KODEBARANG'], detail_row['SATUAN'])
                        if item_tuple in processed_items:
                            continue
                        processed_items.add(item_tuple)

                        score = fuzz.ratio(query_name, detail_row['NAMABRG'])
                        match_results.append({
                            "Barang Mirip di Data SJ": detail_row['NAMABRG'],
                            "Skor Kemiripan (%)": score,
                            "Harga Rata-Rata": detail_row.get(f"HARGARATA", 0),
                            "Kode": detail_row.get("KODEBARANG", "N/A"),
                            "Kategori": detail_row.get("KATEGORI", "N_A"),
                            "Satuan": detail_row.get("SATUAN", "N_A"),
                            "Permintaan Awal": detail_row.get("Permintaan_Awal", pd.NaT),
                            "Permintaan Terakhir": detail_row.get("Permintaan_Terakhir", pd.NaT)
                        })

                    if not db_df.empty and all(c in db_df.columns for c in ['BARANG_A', 'BARANG_B']):
                        related_a = db_df[db_df['BARANG_A'] == current_name]['BARANG_B'].tolist()
                        related_b = db_df[db_df['BARANG_B'] == current_name]['BARANG_A'].tolist()
                        all_related = set(related_a + related_b)
                        for related_name in all_related:
                            if not any(related_name in item for item in processed_items):
                                names_to_process_queue.append(related_name)

                if match_results:
                    results_df = pd.DataFrame(match_results).drop_duplicates(subset=['Barang Mirip di Data SJ', 'Kode', 'Satuan'])
                    results_df = results_df.sort_values(by="Skor Kemiripan (%)", ascending=False)
                    st.session_state.new_item_results = results_df
                else:
                    st.session_state.new_item_results = pd.DataFrame()
            else:
                st.sidebar.error("Gagal memuat atau memproses Data SJ. Pastikan kolom 'NAMABRG' dan 'SJ_CREATED_ON' ada.")
                st.session_state.new_item_results = None

# --- Menampilkan hasil HANYA jika sudah difilter ---
if st.session_state.filtered_df is not None:
    filtered_df = st.session_state.filtered_df
    st.markdown("---")
    st.header("📋 Hasil Filter")

    if not filtered_df.empty:
        col1, col2 = st.columns(2)
        with col1:
            display_limit_option = st.selectbox(
                "Tampilkan jumlah pasangan:",
                ('100 Teratas', '200 Teratas', 'Seluruh Pasangan'),
                key='display_limit'
            )
        with col2:
            sort_order_option = st.selectbox(
                "Urutkan berdasarkan SCORE:",
                ('Tertinggi ke Terendah', 'Terkecil ke Tertinggi'),
                key='sort_order'
            )

        sort_ascending = (sort_order_option == 'Terkecil ke Tertinggi')
        sorted_df = filtered_df.sort_values(by="SCORE", ascending=sort_ascending)

        if display_limit_option == '100 Teratas':
            display_df_limited = sorted_df.head(100)
            st.write(f"Menampilkan **{len(display_df_limited)} dari {len(sorted_df)}** total pasangan yang cocok.")
        elif display_limit_option == '200 Teratas':
            display_df_limited = sorted_df.head(200)
            st.write(f"Menampilkan **{len(display_df_limited)} dari {len(sorted_df)}** total pasangan yang cocok.")
        else:
            display_df_limited = sorted_df
            st.warning("Perhatian: Menampilkan seluruh pasangan (jika ribuan) dapat memperlambat aplikasi.")
            st.write(f"Menampilkan **{len(display_df_limited)}** total pasangan yang cocok.")

        display_df = display_df_limited[[
            c for c in [
                "SCORE", "SELISIH_HARGA_PERSEN", "BARANG_A", "HARGA_A", "SATUAN", "KODE_A", "KATEGORI_A",
                "BARANG_B", "HARGA_B", "KODE_B", "KATEGORI_B"
            ] if c in sorted_df.columns
        ]]

        styled_df = display_df.style.format({
            'HARGA_A': "Rp {:,.0f}",
            'HARGA_B': "Rp {:,.0f}",
            'SCORE': '{:.2f}',
            'SELISIH_HARGA_PERSEN': '{:.2f}%'
        }).set_properties(
            **{'background-color': '#e8f5e9'},
            subset=[c for c in ["BARANG_A", "BARANG_B"] if c in display_df.columns]
        ).set_properties(
            **{'background-color': "#e3f2fd"},
            subset=[c for c in ["HARGA_A", "HARGA_B"] if c in display_df.columns]
        )

        st.dataframe(styled_df)
    else:
        st.warning("Tidak ada data yang cocok dengan filter Anda.")
else:
    st.info("Pilih filter di sidebar dan klik 'START' untuk memulai.")

# --- Bagian Analisis Detail ---
st.markdown("---")
st.header("🔬 Analisis Detail Barang")
primary_item = st.text_input("Masukkan nama barang untuk dianalisis:", key="detail_search")

if primary_item:
    tab1, tab2 = st.tabs(["Perbandingan Side-by-Side", "Tinjau Data SJ"])

    with tab1:
        st.subheader(f"Mencari pasangan mirip untuk: {primary_item}")
        if not db_df.empty and all(c in db_df.columns for c in ['BARANG_A', 'BARANG_B', 'HARGA_A', 'HARGA_B', 'SATUAN', 'KODE_A', 'KODE_B', 'KATEGORI_A', 'KATEGORI_B']):
            related_pairs = db_df[
                (db_df['BARANG_A'].str.contains(primary_item, case=False, na=False)) |
                (db_df['BARANG_B'].str.contains(primary_item, case=False, na=False))
            ]
        else:
            related_pairs = pd.DataFrame()

        if not related_pairs.empty:
            st.write(f"Ditemukan {len(related_pairs)} pasangan yang mirip di dalam database:")
            for _, row in related_pairs.iterrows():
                is_a_primary = primary_item.upper() in str(row['BARANG_A']).upper()

                item_a_name = row['BARANG_A'] if is_a_primary else row['BARANG_B']
                item_a_price = row['HARGA_A'] if is_a_primary else row['HARGA_B']
                item_a_unit = row['SATUAN']
                item_a_code = row['KODE_A'] if is_a_primary else row['KODE_B']
                item_a_cat = row['KATEGORI_A'] if is_a_primary else row['KATEGORI_B']

                item_b_name = row['BARANG_B'] if is_a_primary else row['BARANG_A']
                item_b_price = row['HARGA_B'] if is_a_primary else row['HARGA_A']
                item_b_unit = row['SATUAN']
                item_b_code = row['KODE_B'] if is_a_primary else row['KODE_A']
                item_b_cat = row['KATEGORI_B'] if is_a_primary else row['KATEGORI_A']

                highlighted_a, highlighted_b = highlight_diff(item_a_name, item_b_name)

                st.markdown("---")
                col1_tab1, col2_tab1 = st.columns(2)
                with col1_tab1:
                    st.markdown("#### Barang Utama")
                    st.markdown(f"**Nama:** {highlighted_a}", unsafe_allow_html=True)
                    if pd.notna(item_a_price):
                        st.markdown(f"**Harga:** Rp {int(item_a_price):,}".replace(',', '.'))
                    st.markdown(f"**Satuan:** {item_a_unit}")
                    st.markdown(f"**Kode:** {item_a_code}")
                    st.markdown(f"**Kategori:** {item_a_cat}")

                with col2_tab1:
                    st.markdown("#### Pasangan Mirip")
                    st.markdown(f"**Nama:** {highlighted_b}", unsafe_allow_html=True)
                    if pd.notna(item_b_price):
                        st.markdown(f"**Harga:** Rp {int(item_b_price):,}".replace(',', '.'))
                    st.markdown(f"**Satuan:** {item_b_unit}")
                    st.markdown(f"**Kode:** {item_b_code}")
                    st.markdown(f"**Kategori:** {item_b_cat}")
        else:
            st.info("Tidak ditemukan pasangan yang mirip di dalam database kemiripan.")

    with tab2:
        st.subheader(f"Mencari riwayat pembelian untuk: {primary_item}")
        include_similar = st.checkbox("Sertakan semua barang yang mirip dalam pencarian riwayat (Skor >= 95%)")

        with st.spinner("Memuat data riwayat pembelian..."):
            sj_df = load_excel_from_drive(FILE_ID_SJ, sheet_name=SHEET_NAME_SJ)

        if not sj_df.empty and 'NAMABRG' in sj_df.columns:
            search_terms = [primary_item]
            if include_similar and not db_df.empty and all(c in db_df.columns for c in ['BARANG_A', 'BARANG_B', 'SCORE']):
                related_pairs_for_sj = db_df[
                    (db_df['BARANG_A'].str.contains(primary_item, case=False, na=False)) |
                    (db_df['BARANG_B'].str.contains(primary_item, case=False, na=False))
                ]
                high_score_pairs = related_pairs_for_sj[related_pairs_for_sj['SCORE'] >= 95]

                if not high_score_pairs.empty:
                    similar_items_a = high_score_pairs['BARANG_A'].tolist()
                    similar_items_b = high_score_pairs['BARANG_B'].tolist()
                    search_terms = list(set([primary_item] + similar_items_a + similar_items_b))

            search_pattern = '|'.join([re.escape(term) for term in search_terms])
            sj_filtered = sj_df[sj_df['NAMABRG'].str.contains(search_pattern, case=False, na=False, regex=True)]

            if not sj_filtered.empty:
                st.write(f"Ditemukan {len(sj_filtered)} riwayat pembelian yang cocok:")
                # --- PERUBAHAN: Tambahkan format currency dan format lainnya di sini ---
                format_dict = {
                    'HARGARATA': 'Rp {:,.0f}',
                    'TOTALHARGA': 'Rp {:,.0f}',
                    'SJ_CREATED_ON': '{:%d/%m/%y}',
                    'JUMLAH': '{:,.0f}',
                    'JMLDISETUJUI': '{:,.0f}',
                    'JML_DITERIMA': '{:,.0f}'
                }
                final_format_dict = {k: v for k, v in format_dict.items() if k in sj_filtered.columns}
                st.dataframe(sj_filtered.style.format(final_format_dict))
            else:
                st.warning(f"Tidak ditemukan riwayat pembelian yang cocok di Data SJ.")
        else:
            st.error("Gagal memuat atau memproses Data SJ.")

# --- Menampilkan Hasil Cek Barang Baru ---
if st.session_state.new_item_results is not None:
    st.markdown("---")
    st.header("🔎 Hasil Pengecekan Histori Nama Barang")
    if not st.session_state.new_item_results.empty:
        st.write(f"Barang yang mirip dengan '{new_item_name}':")

        results_df_display = st.session_state.new_item_results.copy()

        ordered_columns = [
            "Skor Kemiripan (%)",
            "Barang Mirip di Data SJ",
            "Kode",
            "Kategori",
            "Satuan",
            "Harga Rata-rata",
            "Permintaan Awal",
            "Permintaan Terakhir"
        ]
        display_cols = [c for c in ordered_columns if c in results_df_display.columns]
        display_results_df = results_df_display[display_cols]

        # --- PERUBAHAN: Gunakan .style.format untuk tampilan currency dan format lainnya ---
        st.dataframe(
            display_results_df.style.format({
                'Harga Rata-rata': 'Rp {:,.0f}',
                'Skor Kemiripan (%)': '{:.2f}',
                'Permintaan Awal': '{:%d-%m-%Y}',
                'Permintaan Terakhir': '{:%d-%m-%Y}'
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.success(f"Tidak ditemukan barang yang mirip dengan '{new_item_name}' (di atas 50%). Barang ini kemungkinan besar unik.")

