# UI translations

Each file in this folder holds every string of the public caption site for one
interface language. All files must contain exactly the same keys
(`npm test` checks this).

**These translations were written by hand and should be reviewed by native
speakers before relying on them in a service.** Church vocabulary in particular
(service / culto / culte / богослужение / 礼拜 / 예배 …) may need adjusting to
match how your congregation speaks.

## Adding a language

1. Copy `en.json` to `<code>.json` (the same code the backend uses, e.g. `tl`)
   and translate every value. Keep `{{placeholders}}` unchanged.
2. Plurals use i18next v4 suffixes (`_zero`, `_one`, `_two`, `_few`, `_many`,
   `_other`) following the CLDR rules of the language. Always provide `_other`
   and `_one`; add the other forms the language needs.
3. Register the file in `src/i18n.ts` (import it and add it to `locales`).
   If the language is written right to left, also add it to `RTL_UI` there.
4. Run `npm test` and `npm run build`.

Languages that the backend offers but that have no file here still receive
captions; their interface falls back to English.
