# CLAUDE.md — Coding Rules

## Hard rules
1. Jangan membuat PostgreSQL Docker service.
2. Jangan mengekspos PostgreSQL ke Internet.
3. Jangan menaruh WAHA API key di frontend, localStorage, bundle, atau konfigurasi browser.
4. Frontend tidak boleh memanggil WAHA secara langsung.
5. BFF bukan generic URL proxy dan harus memakai allowlist endpoint WAHA.
6. Webhook harus idempotent.
7. Side effect outbound WhatsApp harus memiliki idempotency handling.
8. Jangan mengubah API contract/arsitektur secara diam-diam.
9. Jangan mencampur deployment Tencent dan kantor.
10. Jangan mengerjakan phase berikutnya tanpa diminta.

## Scope
- `frontend/`: React + TypeScript.
- `bff/`: server-side gateway Tencent ke WAHA.
- `backend/`: Django + DRF.
- `infrastructure/tencent/`: deployment Tencent.
- `infrastructure/office/`: deployment kantor.
- `docs/`: specification.

## Workflow
1. Baca dokumen relevan.
2. Nyatakan scope.
3. Inspeksi code yang sudah ada.
4. Implementasikan perubahan terkecil yang koheren.
5. Jalankan test/lint/type-check.
6. Laporkan file berubah, test, dan risiko.
7. Jangan refactor yang tidak terkait.

Jika requirement ambigu dan menyangkut security, data integrity, atau architecture, jangan menebak: tanyakan.

## Offline rule
Office backend/database offline tidak berarti WAHA offline. UI wajib membedakan:
- WAHA
- BFF/Tencent
- office backend
- PostgreSQL
- synchronization status.
