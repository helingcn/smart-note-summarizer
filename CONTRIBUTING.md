# SmartDigest'e katkı

## Başlamadan önce

1. Bir bug veya özellik için önce mevcut issue'ları kontrol edin.
2. Büyük mimari değişikliklerde uygulamaya başlamadan önce bir tasarım issue'su açın.
3. Kullanıcı belgelerini veya API anahtarlarını test verisine eklemeyin.

## Geliştirme kurulumu

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Kontroller

Her pull request öncesinde çalıştırın:

```bash
python -m py_compile backend/*.py frontend/*.py
ruff check backend frontend evals scripts test_extractor.py
ruff format --check backend frontend evals scripts test_extractor.py
mypy backend/models.py frontend/summary_utils.py evals/schemas.py evals/metrics.py
pytest -m "not live_api and not e2e" --cov
pip-audit -r requirements-backend.txt -r requirements-frontend.txt
docker compose config --quiet
```

Docker ile ilgili değişikliklerde:

```bash
docker compose build backend frontend
```

## Kod ve veri kuralları

- Backend davranışını değiştiren kod testle birlikte gelmelidir.
- Özet kalitesini etkileyen değişiklikler sabit değerlendirme veri setinde ölçülmelidir.
- UI metinleri Türkçe, açık ve doğrulanabilir olmalıdır.
- Gizlilik veya saklama davranışı değişiyorsa README de güncellenmelidir.
- Streamlit'in özel DOM seçicilerine bağımlı CSS değişiklikleri farklı ekran
  genişliklerinde kontrol edilmelidir.

## Commit düzeni

Küçük, tek amaçlı ve emir kipinde commit başlıkları kullanın:

```text
feat(auth): add email verification flow
fix(queue): recover expired worker leases
docs: explain encrypted source retention
```

## Pull request

Pull request açıklamasında şunlar bulunmalıdır:

- Problem ve çözüm
- Güvenlik/gizlilik etkisi
- Çalıştırılan testler
- UI değiştiyse ekran görüntüsü
- Bilinen sınırlamalar veya takip işleri
