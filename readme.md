# Dashboard Analisis Konsistensi Harga Barang

## Tentang Dashboard

Dashboard berbasis Streamlit untuk meninjau konsistensi data master barang. Menampilkan pasangan nama barang yang mirip, membantu menemukan duplikasi, beda penulisan, dan anomali harga. Tersedia tampilan riwayat pembelian serta cek nama barang baru sebelum dicatat.

## Fitur

* **Tabel kemiripan**: pasangan barang mirip dari raw data (fuzzy matching).
* **Filter**: skor kemiripan, kategori, jumlah hasil, dan urutan skor.
* **Perbandingan detail**: dua barang ditampilkan berdampingan dengan highlight perbedaan teks.
* **Tinjau riwayat (Data SJ)**: tampilkan transaksi terkait barang/barang mirip.
* **Validasi barang baru**: cek nama baru terhadap data historis untuk cegah duplikasi.

## Cara Kerja (singkat)

* **Viewer saja**: aplikasi hanya menampilkan data yang sudah diproses di luar (hasil matching).
* **Sumber data**: dua file (Excel/Google Sheet) — 1) hasil kemiripan, 2) riwayat SJ.
* **Akses privat**: file diambil dari Google Drive menggunakan **Service Account** + **Streamlit Secrets** (tanpa link publik).

## Tools & Libraries

* **UI**: Streamlit
* **Data**: Pandas, NumPy
* **String matching**: RapidFuzz
* **Google Drive**: google-api-python-client, google-auth
* **Excel**: openpyxl

## Keamanan

* File Drive tetap privat; beri akses **Viewer** hanya ke email **Service Account**.
* Simpan kredensial di `secrets.toml` (Streamlit Secrets). Jangan commit ke repo.
* Scope yang dipakai: `drive.readonly`.

---