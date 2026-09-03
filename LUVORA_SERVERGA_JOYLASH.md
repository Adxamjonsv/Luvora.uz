# Luvora — VDS'ga joylash (24/7 online) — Qo'llanma

Bu qo'llanma botni o'z kompyuteringizdan ajratib, doimiy ishlaydigan serverga (VDS) joylashni ko'rsatadi. Tayyor bo'lgach: bot **24/7 ishlaydi**, manzil **o'zgarmaydi**, cloudflared/PyCharm **kerak emas**.

Kerak bo'ladi: **VDS** (ahost.uz) + **domen** (masalan `luvora.uz`). Mini App uchun HTTPS shart, shuning uchun domen kerak.

---

## 1-qadam — VDS va domen sotib olish (ahost.uz)

1. https://ahost.uz saytiga kiring → ro'yxatdan o'ting.
2. **VDS** bo'limidan tarif tanlang. Minimal yetarli:
   - **1–2 GB RAM**, 1 vCPU, 20+ GB SSD.
   - OS: **Ubuntu 24.04** (yoki 22.04) tanlang.
3. **Domen**: yillik VDS/hosting olsangiz, ko'pincha **1-yil `.uz` domen bepul** beriladi. Alohida olsangiz `.uz` ≈ **27 000 so'm/yil**.
   - Chiroyli nom tanlang: `luvora.uz`, `luvora-app.uz` va h.k.
4. To'lovni yakunlang. Bir necha daqiqada serverga **IP manzil** va **root paroli** email/kabinetga keladi. Ularni saqlab qo'ying.

> Eslatma: Uzbek VDS'da Telegram odatda **VPNsiz** ishlaydi — bu sizning kompyuteringizdagi VPN muammosini ham hal qiladi.

---

## 2-qadam — Domenni serverga yo'naltirish (DNS)

ahost kabinetida domeningizning **DNS** (yoki "A yozuvlari") bo'limiga kiring va 2 ta A-yozuv qo'shing:

| Turi | Nom | Qiymat (IP) |
|------|-----|-------------|
| A | @ | SERVER_IP |
| A | www | SERVER_IP |

`SERVER_IP` — VDS'ingizning IP manzili. Saqlang. (Tarqalishi 5 daqiqadan 24 soatgacha davom etishi mumkin, odatda tez.)

---

## 3-qadam — Serverga ulanish (Windows'dan)

PowerShell'ni oching va yozing (IP ni o'zingiznikiga almashtiring):

```
ssh root@SERVER_IP
```

Parolni so'raydi — kabinetdagi root parolini kiriting (yozganda ko'rinmaydi, shunchaki yozib Enter).

> Parolni **men kirita olmayman** (xavfsizlik) — buni o'zingiz qilasiz.

---

## 4-qadam — Loyiha fayllarini serverga yuklash

Serverda papka yarating:

```
mkdir -p /opt/luvora
```

Endi kompyuteringizdagi **`D:\Новая папка (2)`** ichidagi fayllarni `/opt/luvora` ichiga yuklang. Eng osoni — **WinSCP** (bepul):

1. https://winscp.net dan WinSCP'ni yuklab o'rnating.
2. Ulanish: **SFTP**, Host = SERVER_IP, User = root, parol = root paroli.
3. Chap tomon (kompyuter) → `D:\Новая папка (2)`; o'ng tomon (server) → `/opt/luvora`.
4. Quyidagilarni ko'chiring (drag-drop):
   - `dvinchik_bot.py`
   - `miniapp/` (butun papka)
   - `logo.png`, `welcome.png` (bor bo'lsa)
   - `deploy/` papkasi (deploy.sh, requirements.txt shu yerda)
   - `database.json` (bor bo'lsa — mavjud foydalanuvchilar saqlanadi; bo'lmasa o'zi yaratiladi)

> `cloudflared.exe`, `.venv`, `START.bat`, `tunnel.log` — bularni **yuklamang**, server uchun kerak emas.

---

## 5-qadam — Avtomatik o'rnatish skriptini ishga tushirish

Serverda (SSH oynasida) yozing (domeningizni qo'ying):

```
cd /opt/luvora
sudo bash deploy/deploy.sh luvora.uz
```

Skript o'zi hammasini qiladi: Python, kutubxonalar, **Caddy (avtomatik HTTPS)**, systemd xizmati, portlarni ochish. Oxirida:

```
✅ TAYYOR!  Mini App manzili: https://luvora.uz
```

---

## 6-qadam — Tekshirish

- Brauzerda **https://luvora.uz** oching — Luvora Mini App ochilishi kerak (qulf 🔒 belgili, ya'ni HTTPS ishlayapti).
- Telegramda botga **/start** bosing → "Luvora'ni ochish" tugmasi endi yangi domenni ochadi.
- Bot menyu tugmasi (pastdagi 💞) ham avtomatik yangi manzilга bog'lanadi (bot `webapp_url.txt` dan o'qiydi).

---

## Foydali buyruqlar (serverda)

```
journalctl -u luvora -f        # bot loglarini jonli ko'rish
systemctl restart luvora       # botni qayta ishga tushirish
systemctl status luvora        # holatini ko'rish
```

**Kodni yangilaganда**: WinSCP orqali o'zgargan faylni (`dvinchik_bot.py` yoki `miniapp/index.html`) qayta yuklang, so'ng:

```
systemctl restart luvora
```

---

## Muhim eslatmalar

- **cloudflared / PyCharm / START.bat endi kerak emas** — server o'zi 24/7 ishlaydi.
- Domen — har yili uzaytiriladi (ahost kabinetida).
- Server avtomatik qayta ishga tushsa ham (`Restart=always`), bot o'zi ko'tariladi.
- HTTPS sertifikatni **Caddy avtomatik** oladi va yangilaydi — hech narsa qilish shart emas.
- Fayllarni almashtirgach har doim `systemctl restart luvora`.

Savol bo'lsa — yozing, birga hal qilamiz.
