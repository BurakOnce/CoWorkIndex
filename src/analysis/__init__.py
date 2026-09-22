"""Gerçek AI etkileşimlerinden davranışsal sinyal çıkarımı.

Girdi: bir bağlayıcının gönderdiği ham etkileşim (prompt, cevap, sonraki
prompt = geri bildirim, araç çağrıları, token kullanımı).
Çıktı: `interaction_events` tablosunun alanları + gerekçe.

İki katman:
- `heuristics`: deterministik, model çağırmayan ölçümler (cümle uzunluğu,
  ünlem yoğunluğu, nezaket işaretleri, emir kipi oranı, kural tabanlı
  sınıflandırma).
- `claude_classifier`: yorum gerektiren alanları (kabul/red, itiraz, ikna
  yönü, sonuç, görev tipi, üslup) Claude'a sınıflandırtır; anahtar yoksa
  ya da hata olursa heuristik sonuç kullanılır.
"""
