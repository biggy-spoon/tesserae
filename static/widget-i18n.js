// Optional locale-specific plural forms fall back to the widget's usual text.
export function withPluralForms(t, locale = "en") {
  const translate = t || ((key, fallback) => fallback ?? key);
  const rules = new Intl.PluralRules(locale);
  return (key, fallback, count) => {
    const text = translate(key, fallback);
    return count === undefined ? text : translate(`${key}_${rules.select(count)}`, text);
  };
}
