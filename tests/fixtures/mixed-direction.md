# اتجاهان في مستند واحد

هذا المستند يخلط العربية بالإنجليزية عمدًا. المتن عربي، فاتجاه الصفحة نفسها يجب
أن يكون من اليمين إلى اليسار، بينما تبقى كل فقرة إنجليزية بداخله مقروءة من
اليسار إلى اليمين ومحاذاة إلى اليسار. القائمة والجدول أدناه يجب أن يحتفظا
باتجاه المستند حتى حين يكون نص العنصر إنجليزيًا.

## مصطلحات إنجليزية داخل جملة عربية {#terms}

نستخدم Python و Markdown و WebKit في هذا المشروع، ويجب أن يبقى كل اسم منها
مقروءًا من اليسار إلى اليمين دون أن يبعثر الجملة العربية من حوله، وأن تستقر
النقطة في نهاية الجملة على اليسار.

## شيفرة ومسارات {#code-and-paths}

شغّل الأمر `git status --short` ثم افتح الملف
`~/.config/xedown/settings.json` وتابع العمل كالمعتاد.

المسار المكتوب بلا علامات هو الحالة الوحيدة التي لا يستطيع التنسيق وحده
إصلاحها، لأن لا عنصر حوله يمكن للأنماط أن تمسك به. لذلك يعلّمها الكاتب بنفسه،
بإحدى طريقتين: <bdi>/usr/local/share/xed</bdi> أو
<span dir="ltr">/usr/local/share/xed</span>.

## روابط {#links}

- [صفحة المشروع](https://example.com)
- [/usr/share/doc/xed](https://example.com/doc) — نص الرابط مسار، ويجب ألا
  يسحب معه علامات الترقيم المحيطة به.

## فقرة إنجليزية كاملة {#english}

This paragraph is English inside an Arabic document. It must read left to
right and sit against the left edge of the reading column, while the bullets
of the list below stay on the right, because that is the document's
direction and not this paragraph's.

- عنصر عربي
- An English item, in the same list
- عنصر عربي آخر

## جدول باتجاهين {#table}

| الحقل | Field | القيمة |
| --- | --- | --- |
| الاسم | name | xedown |
| الإصدار | version | 0.2.0 |
| المحرر | editor | xed |

## شيفرة بتعليقات عربية {#fence}

```python
# نقرأ الإعداد ثم نعيد الاتجاه المطلوب
def document_direction(store):
    return store.get("text_direction", "auto")
```
