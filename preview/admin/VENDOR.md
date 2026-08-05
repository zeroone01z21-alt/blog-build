# Sveltia CMS المثبّت

- الحزمة: `@sveltia/cms`
- الإصدار: `0.179.0`
- المصدر: `https://registry.npmjs.org/@sveltia/cms/-/cms-0.179.0.tgz`
- نزاهة حزمة npm (SHA-512/Base64):
  `QrODq5D5vIBkHH8pj0xnzRz73o7LGkGPueuVauzH7fTBFeLUZAhVLp8UTkP9L7ST57BVHq4W2BXY/78pyJSzZw==`
- SHA-256 للملف المستضاف محليًا `vendor/sveltia-cms.js`:
  `bc0fd1a08e46fc6b80d5dc4c90951bb0eeed346ce8fbadb7dd6dd230379abc03`
- SRI المستخدم في `index.html` (SHA-384/Base64):
  `mVjEYeNjgFrDMldKYRXtGqYoTQX7l0LLf7wSUABCSIcQqRQPQckldCncpzRv0zHF`
- الترخيص: MIT، ونسخته في `vendor/SVELTIA-CMS-LICENSE.txt`.

رُقّيت الحزمة من v0.164.2 لأن الإصدارات الأقدم من v0.167.3 متأثرة بثغرة
[GHSA-h5jc-78hr-3pc9](https://github.com/advisories/GHSA-h5jc-78hr-3pc9)
في معاينة Markdown/RichText. الإصدار المثبّت يتجاوز النسخة المصححة.

تم التحقق من نزاهة أرشيف npm قبل استخراج ملف JavaScript. ملف Sveltia التنفيذي
الأساسي محلي وليس محمّلًا من CDN؛ قد تطلب الحزمة موارد أو تبعيات اختيارية من
`jsDelivr` و`unpkg` أثناء التشغيل. عند ترقية Sveltia يجب تحديث الملف والقيم
الثلاث أعلاه والـSRI في `index.html` معًا، ثم تشغيل
`python3 tools/check_cms.py`.
