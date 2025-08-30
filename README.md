# ME-lite: Pavement Performance and Cost Estimation Model

## فكرة البرنامج
ME-lite هو نموذج حتمي لتقدير أداء الرصف وتكاليفه، مصمم لدمج تأثيرات معدلات البيتومين، البلاستيك، المطاط، وظروف التشغيل (درجة الحرارة، الحمل). البرنامج مكتوب بلغة Python وله واجهة رسومية (GUI) للتفاعل.

## المعادلات الرياضية المستخدمة

### 1. الحسابات الأساسية
- **الحجم (V)**: \( V = L \times W \times h \)
- **الكتلة الكلية (M_mix)**: \( M_{\text{mix}} = \rho_m \times V \)
- **كتلة البيتومين (M_bit)**: \( M_{\text{bit}} = P_b \times M_{\text{mix}} \)
- **كتلة البلاستيك (M_pl)**: \( M_{\text{pl}} = P_p \times M_{\text{bit}} \) (نسبة من كتلة البيتومين)
- **كتلة المطاط (M_rub)**: \( M_{\text{rub}} = P_r \times M_{\text{bit}} \) (نسبة من كتلة البيتومين)
- **كتلة الركام (M_agg)**: \( M_{\text{agg}} = M_{\text{mix}} - M_{\text{bit}} \)

### 2. تأثير درجة الحرارة
- **معامل التصحيح (f_T)**: \( f_T = \exp[-k \times (T - T_0)] \)
  (الثوابت: \( k = 0.025 \), \( T_0 = 25 \))

### 3. معامل المرونة (E)
- \( E = E_0 \times f_T \times \frac{1 + p \times P_p}{1 + r \times P_r} \)
  (الثوابت: \( E_0 = 3500 \), \( p = 1.8 \), \( r = 0.8 \))
- **الحدود**: \( E = \max(500, \min(15000, E)) \)

### 4. الإجهادات
- **إجهاد الشد (ε_t)**: \( \varepsilon_t = k_{\varepsilon_t} \times \frac{1}{E} \times \frac{1}{h} \)
  (الثابت: \( k_{\varepsilon_t} = 0.028 \))
- **إجهاد الضغط (ε_c)**: \( \varepsilon_c = k_{\varepsilon_c} \times \frac{1}{E} \)
  (الثابت: \( k_{\varepsilon_c} = 0.005 \))

### 5. العمر التصميمي
- **سعة التعب (N_f)**: \( N_f = k_f \times \varepsilon_t^{-m_f} \)
- **سعة التشوه (N_r)**: \( N_r = k_r \times \varepsilon_c^{-m_r} \)
- **العمر بالسنوات**: \( \text{Life} = \frac{\min(N_f, N_r)}{A} \)

### 6. التكاليف
- **تكلفة الركام**: \( \text{Cost}_{\text{agg}} = M_{\text{agg}} \times c_{\text{agg}} \)
- **تكلفة البيتومين**: \( \text{Cost}_{\text{bit}} = (M_{\text{bit}} - M_{\text{pl}} - M_{\text{rub}}) \times c_{\text{bit}} \)
- **تكلفة البلاستيك**: \( \text{Cost}_{\text{pl}} = M_{\text{pl}} \times c_{\text{pl}} \)
- **تكلفة المطاط**: \( \text{Cost}_{\text{rub}} = M_{\text{rub}} \times c_{\text{rub}} \)
- **التكلفة الإجمالية**: \( \text{Total Cost} = \sum \text{Costs} + \text{Overhead} \)

## كيفية التشغيل
1. **الواجهة الرسومية (GUI)**:
   ```bash
   python gui.py
   ```
2. **واجهة الأوامر (CLI)**:
   ```bash
   python cli.py
   ```

## ملفات البرنامج
- `config.py`: الثوابت الافتراضية.
- `inputs.py`: التحقق من صحة المدخلات.
- `equations.py`: المعادلات الرياضية.
- `model.py`: الدالة الرئيسية لتشغيل النموذج.
- `gui.py`: الواجهة الرسومية.
- `cli.py`: واجهة الأوامر.
- `test.py`: اختبار تشغيلي.
- `notebook.ipynb`: مثال تفاعلي.

## المتطلبات
- Python 3.8+
- حزم Python: `tkinter`

## التوثيق
يتم توثيق الثوابت والمعادلات في ملف `README.md` و docstrings داخل الكود.
