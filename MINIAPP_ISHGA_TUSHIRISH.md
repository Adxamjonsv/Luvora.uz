# Luvora Mini App — ishga tushirish (cloudflared bilan)

Mini App kompyuteringdagi bot ichida web-server ochadi (port 8080).
Telegram faqat `https://` manzilni ochadi, shuning uchun cloudflared tunnel bilan
o'sha web-serverga vaqtincha https manzil beramiz.

## 1. Tunnelni ishga tushirish (cloudflared o'zi yuklanadi)

Papkadagi **`tunnel_ochish.bat`** faylni ikki marta bos.

Birinchi marta cloudflared yo'q bo'lsa, .bat uni **avtomatik yuklab oladi**
(~30 MB, bir marta) va shu papkaga `cloudflared.exe` qilib saqlaydi.
Keyingi safar to'g'ridan-to'g'ri ishlaydi.

> Eslatma: Windows "SmartScreen" ogohlantirsa — "Batafsil / Baribir ishga tushir"
> ni bos (cloudflared Cloudflare'ning rasmiy vositasi).

Bir necha soniyada shunday manzil chiqadi:

```
https://kimdir-nimadir-1234.trycloudflare.com
```

Shu manzilni **nusxala**.

## 3. Manzilni qo'yish (oson usul)

**`webapp_url.txt`** faylini ochib, ichiga faqat shu manzilni yoz (# siz, bitta qator):

```
https://kimdir-nimadir-1234.trycloudflare.com
```

Saqla. (Bot .py faylini tahrirlash shart emas — botni har safar shu fayldan o'qiydi.)

## 4. Botni ishga tushirish

PyCharm'da botni ▶️ ishga tushir. Loglarda ko'rasan:

```
Mini App web-server: http://127.0.0.1:8080 (WEBAPP_URL=https://...)
```

## 5. Ochish

Telegram'da botga kir:
- Xabar yozish maydoni yonidagi **menyu tugmasi (💞 Luvora)** ni bos, YOKI
- `/app` yozib, chiqqan **"💞 Luvora'ni ochish"** tugmasini bos.

Mini App ochiladi: chapga/o'ngga surib (swipe) anketalarni ko'rasan,
❤️ layk, 💬 xabar, ✖ o'tkazish. Pastda **Layklar** va **Profil** bo'limlari.

---

### Muhim eslatmalar
- Ro'yxatdan o'tish va video-krujok tekshiruvi **bot chatida** qoladi
  (webapp ichida krujok yozib bo'lmaydi — bu Telegram cheklovi).
- `trycloudflare` manzili **har safar tunnel qayta ishga tushganda o'zgaradi**.
  O'zgarса, 3-qadamни qaytar (WEBAPP_URL ni yangila).
- Doimiy manzil kerak bo'lса — doimiy hosting yoki cloudflare named tunnel sozlaymiz.
- Kompyuter yoki tunnel o'chsa, Mini App ochilmaydi (bot oddiy rejimda ishlayveradi).
