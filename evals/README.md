# SmartDigest değerlendirme sistemi

Bu klasör, özet ve belge sohbeti değişikliklerini aynı **altın veri seti** üzerinde
tekrarlanabilir biçimde karşılaştırır. Canlı modele çağrı yapmaz; `candidate`
alanına kaydedilmiş SmartDigest çıktısını ölçer.

## Çalıştırma

```bash
cd SmartDigest
source .venv/bin/activate
python scripts/run_evaluation.py evals/datasets/sample.json
```

Raporlar `evals/reports/latest/report.json` ve `report.md` altında oluşur.

## Yeni gerçek belge ekleme

1. PDF'den çıkan `[Sayfa N]` işaretli metni `source_text` alanına koyun.
2. Belgeyi okuyup `expected.facts`, `expected.numbers` ve `expected.qa` alanlarını
   insan tarafından doğru kabul edilen değerlerle doldurun.
3. SmartDigest çıktısını `candidate.summary` ve `candidate.qa` alanlarına yapıştırın.
4. Aracı tekrar çalıştırın ve önceki raporla karşılaştırın.

`direction`, artış için `up`, azalış için `down` değerini alır. Taranmış bir
belgede `expected.ocr_reference` ve `candidate.ocr_text` verilirse OCR kelime hata
oranı da hesaplanır.

## Önemli sınır

Bu ilk sürümde bilgi kapsamı sözcük örtüşmesiyle, kanıt desteği ise mevcut BM25
mekanizmasıyla ölçülür. Bunlar anlamsal doğruluk olasılığı değildir. Veri seti,
sonraki NLI/embedding geliştirmelerinin ölçülebileceği sabit bir başlangıç çizgisi
oluşturur.

Kararsız iddialarda Gemini embedding ve NLI doğrulamasını açmak için:

```bash
python scripts/run_evaluation.py evals/datasets/real_turkish_pdfs.json \
  --semantic --output evals/reports/semantic
```

Bu mod API kullanır. Sayı, yön ve olumsuzluk gibi deterministik çelişki
kontrolleri NLI kararından önce uygulanır ve model tarafından geçersiz kılınmaz.
