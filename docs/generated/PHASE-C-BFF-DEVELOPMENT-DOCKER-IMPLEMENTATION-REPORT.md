# Phase C — BFF Development Docker — Implementation Report

**Ringkasan.** Implementasi Phase C, mengikuti
`docs/generated/PHASE-C-BFF-DEVELOPMENT-DOCKER-DESIGN-AUDIT-REPORT.md`.
Hanya BFF development stack yang diimplementasikan — sesuai instruksi,
`infrastructure/development/tencent.yml` **hanya** berisi service `bff`
(tidak ada Django, Celery, Redis, PostgreSQL, WAHA, atau frontend). Phase
A dan Phase B **tidak diubah** — dikonfirmasi utuh sebelum dan sesudah
(Bagian 3). Tidak ada perubahan permanen pada application source code
(satu perubahan verifikasi sementara pada `bff/src/index.ts` dibuat dan
**dikembalikan persis seperti semula** sebelum laporan ini ditulis —
Bagian 6). Tidak ada dependency baru. Tidak ada `.env` nyata yang
dikomit. Tidak ada pesan WhatsApp dikirim, tidak ada endpoint production
dipanggil, tidak ada database schema disentuh.

---

## 1. Apa yang Diimplementasikan

```
infrastructure/development/
├── office.yml            # Phase B — TIDAK DIUBAH
├── .env.example            # Phase B — TIDAK DIUBAH
├── tencent.yml            # BARU — Phase C
└── tencent.env.example     # BARU — Phase C
```

`tencent.yml` berisi **satu** service (`bff`), dibangun dari
`bff/Dockerfile` yang **tidak dimodifikasi**, menjalankan `tsx watch`
(hot-reload sungguhan, dikonfirmasi hidup di Bagian 7), terhubung ke
Django development container (Phase B) melalui
`http://host.docker.internal:8000` — **bukan** nama service Docker,
**bukan** shared network dengan `office.yml`.

---

## 2. Arsitektur

- **`bff/Dockerfile` dipakai apa adanya**, dengan `build.target: build`
  (stage pertama dari Dockerfile dua-stage yang sudah ada) — stage ini
  sudah menjalankan `npm install` penuh (termasuk `devDependencies`,
  termasuk `tsx`) sebelum langkah `RUN npm run build`-nya sendiri.
  **Tidak dibuat `bff/Dockerfile.dev`** — dikonfirmasi tidak diperlukan,
  persis sesuai audit desain.
- **Command override**: `npx tsx watch src/index.ts` — **bukan**
  `npm run dev`. Alasan eksplisit (didokumentasikan langsung di dalam
  `tencent.yml`): script `npm run dev` yang sudah ada memanggil
  `tsx watch --env-file-if-exists=.env src/index.ts`, dan flag
  `--env-file-if-exists=.env` itu akan memuat `bff/.env` versi host
  (jika developer punya satu untuk workflow bare-host) yang ikut
  ter-bind-mount ke dalam container — berpotensi bertabrakan secara
  tidak terduga dengan environment yang sudah disuntikkan Compose lewat
  `env_file:`. Menjalankan `tsx watch` langsung (tanpa flag tersebut)
  meniru persis cara `CMD` production (`node dist/index.js`, juga tanpa
  flag `--env-file`) sudah bekerja — konsisten dengan pola yang sudah
  ada, bukan mekanisme baru.
- **Bind mount**: `../../bff:/app`, plus **anonymous volume**
  `/app/node_modules` di atasnya — mencegah `node_modules` hasil
  `npm install` di image (yang sudah benar, sudah berisi `tsx`) tertimpa
  oleh isi `bff/node_modules` di host (yang mungkin kosong atau berbeda
  platform).
- **Jaringan**: `tencent.yml` memakai network default Compose miliknya
  sendiri — **tidak ada `networks:` yang di-share dengan `office.yml`**.
  BFF menjangkau Django lewat `http://host.docker.internal:8000`
  (port yang sudah dipublikasikan Phase B), persis mekanisme yang sama
  yang sudah dipakai production untuk hop BFF→Django (NetBird/LAN di
  sana; `host.docker.internal` di sini) — **tanpa perubahan kode sama
  sekali**, dikonfirmasi langsung dari `bff/src/djangoClient.ts` (audit
  desain Bagian 6) dan diverifikasi ulang secara live di Bagian 7 di
  bawah.
- **Nama project Compose eksplisit**: `name: wamora-dev-tencent` di
  bagian atas `tencent.yml` — **temuan konkret dari verifikasi
  langsung**, bukan sesuatu yang diantisipasi di audit desain (lihat
  Bagian 6).

---

## 3. Konfirmasi Phase A/Phase B Tidak Berubah

**Dibaca ulang secara penuh sebelum implementasi dimulai, dan
dikonfirmasi lagi lewat `git status`/`git diff` setelah selesai:**

- `infrastructure/office/.env.example` (Phase A): baris
  `RECONCILIATION_EXECUTOR=celery` masih ada, tidak disentuh ulang oleh
  task ini — muncul di `git diff` hanya karena perubahan Phase A yang
  memang sudah ada dari sesi sebelumnya.
- `infrastructure/development/office.yml` (Phase B): **byte-identik**
  dengan versi yang dibaca di awal task ini — tidak ada perubahan.
- `infrastructure/development/.env.example` (Phase B): **byte-identik**
  — tidak ada perubahan, tidak ditimpa oleh file Tencent yang baru
  (nama file berbeda, `tencent.env.example`, sesuai instruksi eksplisit
  "jangan reuse nama file ini untuk Tencent").

---

## 4. File yang Dibuat/Diubah

**Dikonfirmasi via `git status --short` dan `git diff --stat` setelah
implementasi selesai:**

```
?? infrastructure/development/tencent.yml            (baru)
?? infrastructure/development/tencent.env.example     (baru)
```

**Tidak ada file lain yang berubah** dibanding state sebelum task ini
dimulai (dibandingkan dengan `git status` yang direkam di awal task —
identik, hanya `infrastructure/development/` yang bertambah isi).
Secara khusus, dikonfirmasi **tidak berubah**:
`infrastructure/development/office.yml`,
`infrastructure/development/.env.example`, seluruh isi
`infrastructure/office/`, source backend, source frontend,
database/migration, dan kedua Compose file production
(`infrastructure/office/docker-compose.yml`,
`infrastructure/tencent/docker-compose.yml`).

**`.gitignore`** yang sudah ada dari Phase B (pola `celerybeat-schedule`)
sudah cukup — tidak perlu tambahan pola baru untuk Phase C.

---

## 5. Environment Variables

**`infrastructure/development/tencent.env.example`** memakai nama
variable BFF yang sudah ada persis (dikonfirmasi dari `bff/src/config.ts`,
tidak ada yang dikarang): `PORT`, `WAHA_BASE_URL`, `WAHA_API_KEY`,
`CORS_ALLOWED_ORIGIN`, `WAHA_SESSION_NAME`, `JWT_PUBLIC_KEY`(`_PATH`),
`JWT_ISSUER`, `JWT_AUDIENCE`, `DJANGO_INTERNAL_BASE_URL`,
`INTERNAL_SERVICE_KEY`, `DJANGO_INTERNAL_TIMEOUT_MS`, `WAHA_TIMEOUT_MS`.

**Nilai yang di-pre-fill secara sengaja** (bukan tebakan, sesuai
instruksi eksplisit task):
- `DJANGO_INTERNAL_BASE_URL=http://host.docker.internal:8000` — nilai
  wajib sesuai instruksi, bukan secret, aman untuk template.
- `CORS_ALLOWED_ORIGIN=http://localhost:5173` — sama seperti default
  `bff/.env.example` yang sudah ada.
- Field lain (`WAHA_BASE_URL`, `WAHA_API_KEY`, `JWT_PUBLIC_KEY`,
  `INTERNAL_SERVICE_KEY`, dll.) **dikosongkan**, sama seperti konvensi
  setiap `.env.example` lain di proyek ini — tidak ditebak.

**`INTERNAL_SERVICE_KEY`**: dikonfirmasi (Bagian 7 audit desain, ulang
di sini) boleh berupa nilai lokal terpisah dari production, **asalkan
sama** dengan nilai yang di-set di `infrastructure/development/.env`
(Office stack, Phase B) — kedua file development ini harus disinkronkan
manual oleh developer, persis pola yang sudah ada untuk `bff/.env` +
`backend/.env` di workflow bare-host.

**Penamaan file**: `tencent.env.example` (bukan `.env.example`) — sesuai
instruksi eksplisit, untuk menghindari tabrakan dengan file Phase B yang
sudah ada di direktori yang sama.

---

## 6. Temuan Konkret Baru Selama Verifikasi (Di Luar Prediksi Audit Desain)

**Dua temuan nyata, ditemukan lewat verifikasi langsung, bukan
diprediksi sebelumnya:**

1. **Tabrakan nama project Compose.** `office.yml` dan `tencent.yml`
   berada di direktori yang sama (`infrastructure/development/`). Docker
   Compose menentukan nama project dari nama direktori jika tidak
   diberikan eksplisit — artinya **keduanya akan default ke nama project
   yang sama** ("development"), yang akan **menyatukan** service `bff`
   ke dalam network/project milik `office.yml` secara diam-diam,
   bertentangan langsung dengan desain "tidak ada shared network."
   **Ditangani** dengan menambahkan `name: wamora-dev-tencent` secara
   eksplisit di bagian atas `tencent.yml` (satu-satunya file yang
   diubah untuk ini — `office.yml` tidak disentuh). Setelah perbaikan,
   `docker compose -f tencent.yml up` membuat network
   `wamora-dev-tencent_default` yang benar-benar terpisah dari
   `development_default` milik `office.yml` — dikonfirmasi lewat
   `docker compose config` dan `docker network ls` selama verifikasi.
2. **`tsx watch` tidak mendeteksi perubahan file lewat bind mount di
   environment verifikasi ini** (Docker Desktop di Windows), meskipun isi
   file dan mtime-nya **terbukti** ter-sinkron benar ke dalam container
   (dicek langsung: `stat` di dalam container menunjukkan mtime yang
   identik dengan host). Ini bukan kegagalan bind mount, melainkan
   watcher `tsx` (berbasis `chokidar`) yang tidak menerima event
   filesystem native dari mekanisme sharing Docker Desktop di
   environment ini — kelas masalah yang sudah dikenal luas untuk
   tool berbasis inotify di atas bind mount Docker-on-Windows.
   **Ditangani tanpa dependency baru**: `chokidar` (dependency tsx yang
   sudah ada) mengenali variable environment standar
   `CHOKIDAR_USEPOLLING` — ditambahkan sebagai `environment:
   CHOKIDAR_USEPOLLING: "true"` di `tencent.yml`. Setelah ini, hot
   reload terbukti bekerja (Bagian 7).

Keduanya adalah perbaikan pada **file baru milik Phase C sendiri**
(`tencent.yml`) — **bukan** perubahan pada Phase B atau Phase A.

---

## 7. Hasil Verifikasi

**Semua dijalankan sungguhan (Docker Desktop tersedia), bukan asumsi:**

1. **`docker compose -f infrastructure/development/tencent.yml config`
   valid** — tidak ada error syntax, environment ter-propagate benar.
2. **Build BFF berhasil** — image `wamora-bff-dev` ter-build dari
   `bff/Dockerfile` **yang tidak diubah**, target `build`; `167 packages`
   ter-install (dependencies + devDependencies, termasuk `tsx`),
   `tsc -p tsconfig.json` sukses.
3. **Stack Tencent start**: container `wamora-dev-tencent-bff-1` `Up
   (healthy)` — healthcheck (`GET /health` via Node's built-in `http`
   client, bukan curl/wget, sesuai instruksi tidak menambah dependency
   baru) lolos.
4. **Proses yang benar-benar berjalan dikonfirmasi via `ps aux` di
   dalam container**: `tsx watch src/index.ts` → `node .../tsx/dist/loader.mjs` →
   `esbuild --service`. **Bukan** `node dist/index.js` (compiled) —
   dikonfirmasi ini benar proses development, bukan production.
5. **BFF merespons di host**: `curl http://localhost:8081/health`
   (port sementara untuk verifikasi, lihat Bagian 8) → `HTTP 200`,
   `{"status":"ok","service":"bff","waha":{"reachable":false}}` (`false`
   karena `WAHA_BASE_URL` sengaja dikosongkan di environment
   verifikasi — sesuai ekspektasi, bukan bug).
6. **BFF → Django terkonfirmasi tersambung lewat
   `http://host.docker.internal:8000`**: dari **dalam** container BFF
   (project Compose `wamora-dev-tencent`, sepenuhnya terpisah dari
   project `development` milik Office), memanggil endpoint liveness
   Django (`/api/health/`, dari stack Office/Phase B yang dijalankan
   bersamaan) → `status=200 body={"status":"ok","component":"backend"}`.
   **Ini membuktikan langsung**: dua Compose project yang benar-benar
   terpisah (network berbeda, tanpa shared network apa pun) tetap bisa
   saling terhubung lewat host-published port, persis desain yang
   diminta.
7. **Hot reload terverifikasi dengan perubahan source yang aman, tidak
   mengubah behavior**: menambahkan satu baris komentar ke
   `bff/src/index.ts`, mengonfirmasi `tsx watch` mendeteksinya
   (`[tsx] change in ./src/index.ts Restarting...` di log, proses
   restart, `bff listening on port 8080` muncul kedua kalinya) — **lalu
   mengembalikan file persis seperti semula** sebelum lanjut ke langkah
   berikutnya (dikonfirmasi via `git status`/pembacaan ulang file,
   Bagian 3/Bagian 4 tidak menunjukkan `bff/src/index.ts` sebagai
   berubah).
8. **`npm run typecheck`, `npm run build`, `npm test` dijalankan di
   dalam container** (bukan di host) — semua sukses: `tsc --noEmit`
   bersih, `tsc -p tsconfig.json` bersih, **110/110 test lolos**
   (`vitest run`).
9. **Tidak ada pesan WhatsApp dikirim, tidak ada endpoint production
   dipanggil** — `WAHA_BASE_URL` kosong di environment verifikasi;
   satu-satunya panggilan jaringan yang dilakukan adalah ke Django
   development container milik Phase B (poin 6 di atas) dan ke BFF
   sendiri (poin 5).
10. **Tidak ada database schema disentuh** — tidak ada migration
    dijalankan pada task ini (BFF tidak punya database sendiri).
11. **Phase A/Phase B tidak diubah** — dikonfirmasi Bagian 3.
12. **Shutdown bersih**: `docker compose down` pada kedua stack
    (`tencent.yml` lalu `office.yml`) menghapus seluruh
    container/network tanpa sisa.

---

## 8. Catatan Verifikasi: Port Sementara

Port host `8080` **sudah dipakai proses lain di mesin ini** (tidak
terkait proyek Wamora — dikonfirmasi lewat `netstat`, PID milik proses
Windows lain, bukan container Docker milik proyek ini). Untuk
menyelesaikan verifikasi tanpa mengubah mesin developer (tidak
menghentikan proses tak terkait milik orang lain di mesin yang sama),
`tencent.yml` **sementara** diubah ke `8081:8080` selama pengujian, lalu
**dikembalikan ke `8080:8080`** (port yang benar, sesuai dokumentasi
proyek — `bff/.env.example`, `bff/Dockerfile`'s `EXPOSE 8080`,
`infrastructure/tencent/docker-compose.yml`'s `"8080:8080"`) sebelum
laporan ini ditulis. **File final yang dikomit memakai `8080:8080`** —
dikonfirmasi lewat `docker compose config` setelah revert (Bagian 7,
poin 1) dan pembacaan ulang file.

---

## 9. Keterbatasan yang Diketahui

- **`CHOKIDAR_USEPOLLING=true` memakai polling**, bukan event filesystem
  native — sedikit lebih boros CPU dibanding watcher berbasis event,
  tapi ini satu-satunya cara yang terbukti bekerja di environment
  verifikasi ini (Docker Desktop/Windows); developer di environment lain
  (mis. Docker native di Linux, atau WSL2 dengan konfigurasi berbeda)
  mungkin tidak membutuhkan ini, tapi membiarkannya aktif tidak
  merugikan (chokidar's polling tetap benar secara fungsional di semua
  platform, hanya sedikit kurang efisien).
- **`host.docker.internal` portability**: sama seperti Phase B, bekerja
  langsung di Docker Desktop (environment sesi ini) — di Linux Docker
  Engine native perlu tambahan `extra_hosts` (tidak dikonfigurasi di
  `tencent.yml` untuk task ini, sesuai environment sesi ini adalah
  Docker Desktop).
- **Dua `.env` terpisah harus disinkronkan manual**
  (`infrastructure/development/.env` untuk Office,
  `infrastructure/development/tencent.env` untuk Tencent) —
  `INTERNAL_SERVICE_KEY` harus sama persis di keduanya, sama seperti
  keterbatasan yang sudah ada di workflow bare-host (`bff/.env` +
  `backend/.env`), bukan sesuatu yang baru diperkenalkan task ini.
- **Frontend belum punya Docker development environment** — sesuai
  scope eksplisit task ini, sengaja tidak dikerjakan.
- **Verifikasi ini tidak memakai WAHA nyata** (`WAHA_BASE_URL` kosong)
  — endpoint yang benar-benar memanggil WAHA (mis. session lifecycle)
  belum diverifikasi end-to-end dengan WAHA sungguhan pada task ini.

---

## 10. Ringkasan Jawaban Eksplisit

- **Apakah source code diubah secara permanen?** Tidak. Satu perubahan
  sementara pada `bff/src/index.ts` (komentar, untuk verifikasi hot
  reload) dibuat dan **dikembalikan persis seperti semula** sebelum
  laporan ini selesai — dikonfirmasi via `git status` menunjukkan file
  tersebut tidak berubah.
- **Apakah `bff/Dockerfile.dev` dibuat?** Tidak — Dockerfile yang sudah
  ada terbukti cukup lewat `build.target: build`, sesuai preferensi
  eksplisit instruksi.
- **Apakah dependency baru ditambahkan?** Tidak — `CHOKIDAR_USEPOLLING`
  adalah environment variable yang sudah dikenali `chokidar` (dependency
  `tsx` yang sudah ada), bukan package baru.
- **Apakah Phase A/Phase B diubah?** Tidak — dikonfirmasi Bagian 3.
- **Apakah database/WAHA state disentuh?** Tidak.
- **Apakah konfigurasi production diubah?** Tidak —
  `infrastructure/tencent/docker-compose.yml` dan
  `infrastructure/office/docker-compose.yml` tidak disentuh sama sekali.

---

## 11. Rekomendasi Fase Berikutnya

**Tidak diimplementasikan pada task ini** — hanya dicatat:

1. Frontend development Docker (Phase D) — independen, tidak
   memblokir apa pun dari Phase C.
2. Keputusan yang masih terbuka dari audit desain Phase C Bagian 15
   (mis. apakah healthcheck BFF ini perlu dipertahankan jangka panjang
   — sudah diimplementasikan di task ini karena endpoint `/health` yang
   sudah ada memang cocok, sesuai aturan eksplisit instruksi).

**STOP — Phase C (BFF-only) selesai.** Tidak melanjutkan ke Phase D,
Phase 9.1C, atau pekerjaan lain yang tidak diminta pada task ini.
