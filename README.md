# ME-lite: نموذج تقدير أداء وتكلفة الرصف مع انترو فيديو وصوت

## فكرة البرنامج
ME-lite برنامج بايثون لتقدير أداء رصف الطرق وتكلفته المادية. يوفر واجهة رسومية حديثة، رسوم بيانية، وتصدير نتائج التشغيل إلى ملف `runs/*.json`. قبل فتح الواجهة، يتم تشغيل انترو فيديو 16 ثانية بملء الشاشة بدون حدود، ويمكن دمج موسيقى خلفية معه.

## المزايا الرئيسية
- واجهة رسومية حديثة مبنية بـ `customtkinter` مع بطاقات مؤشرات ورسوم بيانية تفاعلية.
- تشغيل انترو فيديو بملء الشاشة بدون حدود باستخدام `ffplay` أو VLC، مع دعم دمج موسيقى.
- دعم تكوينات جاهزة من `standards.json` مع قفل المدخلات حتى اختيار Preset (اختياري).
- تصدير نتائج التشغيل إلى `runs/*.json` للاحتفاظ بالتقارير.

## التثبيت (Windows/PowerShell)
1) إنشاء بيئة عمل وتفعيلها:
```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
./.venv/Scripts/Activate.ps1
```
2) تثبيت المتطلبات:
```powershell
pip install -r requirements.txt
```
3) أدوات اختيارية للانترو (لأفضل عرض بملء الشاشة):
- يوصى بتثبيت FFmpeg (لأجل `ffplay`) أو VLC.
- يمكن تعريف مسارها عبر المتغيرات:
  - `FFPLAY_PATH` (مثال: `C:\\ffmpeg\\bin\\ffplay.exe`)
  - `VLC_PATH` (مثال: `C:\\Program Files\\VideoLAN\\VLC\\vlc.exe`)

## إنشاء انترو الفيديو (للمبتدئين خطوة بخطوة)
اتبع هذه الخطوات البسيطة لإنتاج فيديو انترو 16 ثانية كامل مع الصوت والشعارات:
- __[1] حضّر الملفات__
  - ملف صوت: `intro_music.mp3` (ضعه داخل نفس مجلد المشروع).
  - شعارات (اختياري): `azhar_logo.png`, `faculty_logo.png`, `team_logo.png`, `app_logo.png`.
  - خطوط (اختياري جدًا): يمكنك عدم تحديدها وسيختار البرنامج خطًا مناسبًا تلقائيًا.

- __[2] الطريقة السريعة جدًا (بدون تحديد خطوط/شعارات)__
  ينشئ فيديو 1080p جاهز:
  ```powershell
  python intro_video.py --out runs/intro1080.mp4 --music intro_music.mp3 --w 1920 --h 1080 --fps 30
  ```

- __[3] أمر كامل بكل الخيارات (استخدم مسارات كاملة لو عندك ملفات في أماكن مختلفة)__
  غيّر المسارات بما يناسب جهازك. لو اسم المجلد فيه مسافات، حُط المسار بين علامات اقتباس "":
  ```powershell
  python intro_video.py `
    --out "runs/intro1080_full.mp4" `
    --music "intro_music.mp3" `
    --w 1920 --h 1080 --fps 30 `
    --logo_azhar "azhar_logo.png" `
    --logo_faculty "faculty_logo.png" `
    --logo_team "team_logo.png" `
    --logo_app "app_logo.png" `
    --font_ar "C:\\Windows\\Fonts\\Tahoma.ttf" `
    --font_en "C:\\Windows\\Fonts\\Arial.ttf"
  ```
  ملاحظة: لو مش عارف تحدد خطوط، الأفضل __ما تستخدمش__ `--font_ar/--font_en` وسيختار البرنامج تلقائيًا.

### أوامر جاهزة لأكثر من جودة
اختر أمر واحد فقط حسب الجودة المطلوبة. كل الأوامر 16 ثانية و30 إطار/ثانية:

- __4K (2160p)__ جودة عالية جدًا:
  ```powershell
  python intro_video.py --out runs/intro2160.mp4 --music intro_music.mp3 --w 3840 --h 2160 --fps 30
  ```

- __Full HD (1080p)__ مناسبة لمعظم الأجهزة:
  ```powershell
  python intro_video.py --out runs/intro1080.mp4 --music intro_music.mp3 --w 1920 --h 1080 --fps 30
  ```

- __HD (720p)__ أخف وأسرع رندر:
  ```powershell
  python intro_video.py --out runs/intro720.mp4 --music intro_music.mp3 --w 1280 --h 720 --fps 30
  ```

- __SD (480p)__ لأجهزة ضعيفة جدًا:
  ```powershell
  python intro_video.py --out runs/intro480.mp4 --music intro_music.mp3 --w 854 --h 480 --fps 30
  ```

### نصائح مهمة
- لو المسار فيه مسافات (مثل Program Files) لازم تكتب المسار بين "".
- عدم تحديد `--font_ar/--font_en` = البرنامج يحاول يختار خطوط موجودة تلقائيًا.
- لو عندك شعارات، ضعها بجانب المشروع أو استخدم مسارات كاملة لها.
- إخراج الملف داخل `runs/` يساعدك ترتّب النتائج.

### حل مشكلة الخطوط بسرعة (OSError: cannot open resource)
لو ظهر خطأ بخصوص الخطوط:
- إمّا احذف خيارات `--font_ar/--font_en` ودع البرنامج يختار تلقائيًا.
- أو استخدم مسارات كاملة لخطوط موجودة في ويندوز مثل:
  - عربي: `C:\\Windows\\Fonts\\Tahoma.ttf`
  - إنجليزي: `C:\\Windows\\Fonts\\Arial.ttf`
- بديل: انسخ ملفات الخطوط (`.ttf`) إلى مجلد المشروع واكتب اسم الملف فقط.

## التشغيل
- تثبيت المتطلبات (لو لسه ما ثبتتش):
```powershell
pip install -r requirements.txt
```
- الواجهة الرسومية (GUI):
```powershell
python gui.py
```
سيتم تشغيل الانترو بملء الشاشة بدون حدود إن توفّر `ffplay` أو VLC. إن لم يُعثر عليهما، سيُطلب منك اختيار الملف التنفيذي يدويًا، وإن ألغيت، سيتم فتح الواجهة مباشرة بدون انترو.

- واجهة الأوامر (CLI) مثال كامل:
```powershell
python cli.py --L 1.0 --W 3.5 --h 0.05 --rho_m 2.4 --Pb 0.055 --Pp 0.05 --Pr 0.08 --T 30 --A 1.0 --c_agg 100 --c_bit 500 --c_pl 200 --c_rub 300 --overhead 1000
```

## المتطلبات
- Python 3.10+
- يعتمد المشروع على الحزم في `requirements.txt`، ومنها: `moviepy`, `Pillow`, `numpy`, `arabic-reshaper`, `python-bidi`, `customtkinter`, `matplotlib`, `mplcursors`, `imageio`, `imageio-ffmpeg`.
- أدوات اختيارية للعرض البصري: FFmpeg (`ffplay`) أو VLC لعرض الانترو بدون حدود.

## ملفات المشروع
- `gui.py`: الواجهة الرسومية وتشغيل الانترو بملء الشاشة.
- `model.py`: تنفيذ النموذج وحساب المخرجات.
- `inputs.py`: التحقق من حدود المدخلات.
- `equations.py`: دوال الحساب الأساسية (بدون عرض معادلات هنا).
- `config.py`: الثوابت الافتراضية ونطاقات التشغيل.
- `intro_video.py`: بناء انترو فيديو 16 ثانية وإضافة موسيقى.
- `standards.json`: Presets للمدخلات والحدود.
- `cli.py`: تشغيل من سطر الأوامر.
- `runs/`: ملفات نتائج التشغيل بصيغة JSON.
- `test.py`: مثال تشغيل سريع.

## استكشاف الأخطاء
- الانترو يظهر بحدود/شريط عنوان: ثبّت FFmpeg أو VLC، أو اضبط `FFPLAY_PATH`/`VLC_PATH`.
- لا تظهر الرسوم البيانية: ثبّت `matplotlib` (موجودة ضمن `requirements.txt`).
- مشكلة في الخطوط العربية داخل الانترو: جرّب تحديد خطوط عبر `--font_ar`/`--font_en`.

