# ArabCity Scraper

واجهة ويب محلية وأداة CLI لاستخراج أسماء الأفلام والمسلسلات من كتالوجات ArabCity، مع حساب عدد الحلقات للمسلسلات متى كان الرقم ظاهراً في صفحة التفاصيل أو في صفحة التصنيف.

## التشغيل

```powershell
python arabcity_scraper.py serve --host 127.0.0.1 --port 8765
```

ثم افتح:

```text
http://127.0.0.1:8765
```

## الاستخدام من سطر الأوامر

```powershell
python arabcity_scraper.py scrape --catalog akoam-series-all --pages 1 --details
```

لإخراج JSON:

```powershell
python arabcity_scraper.py scrape --catalog akoam-series-all --pages 1 --details --json
```

## تغيير روابط المواقع

بما أن نطاقات مواقع المشاهدة تتغير كثيراً، يمكن تغيير الروابط بدون تعديل الكود:

```powershell
$env:AKWAM_BASE_URL="https://akwam.cyou"
$env:ALOOYTV_BASE_URL="https://alooytv.co"
```

## ملاحظات

- الأداة تستخرج بيانات الكتالوج فقط: الاسم، النوع، الرابط، وعدد الحلقات للمسلسل إن أمكن.
- إذا كان الموقع يمنع الطلبات أو غيّر بنية HTML، سيظهر الخطأ داخل الواجهة أو نتيجة JSON.
- بعض كتالوجات Akwam القديمة في الـ manifest لا تملك مسارات ثابتة حالياً، لذلك تم ربط المتاح منها بمسارات Akwam الحالية وترك الباقي بأفضل تخمين قابل للتعديل من متغيرات البيئة أو من الكود.