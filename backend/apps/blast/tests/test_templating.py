from django.test import SimpleTestCase

from apps.blast.templating import extract_variable_names, render_template


class ExtractVariableNamesTests(SimpleTestCase):
    def test_extracts_every_distinct_placeholder(self):
        content = 'Yth, {{nama_wp}} Nopol {{nopol}} jatuh tempo {{jatuh_tempo}} sebesar {{nilai_pajak}}'
        self.assertEqual(extract_variable_names(content), {'nama_wp', 'nopol', 'jatuh_tempo', 'nilai_pajak'})

    def test_repeated_placeholder_counted_once(self):
        content = '{{nama}} halo {{nama}} lagi'
        self.assertEqual(extract_variable_names(content), {'nama'})

    def test_no_placeholders_returns_empty_set(self):
        self.assertEqual(extract_variable_names('Halo, pesan biasa tanpa variabel.'), set())

    def test_tolerates_internal_whitespace(self):
        self.assertEqual(extract_variable_names('Halo {{  nama  }}'), {'nama'})

    def test_ignores_malformed_braces(self):
        self.assertEqual(extract_variable_names('Halo {nama} dan {{}} dan {{ }}'), set())


class RenderTemplateTests(SimpleTestCase):
    def test_substitutes_every_placeholder(self):
        content = 'Yth, {{nama_wp}} Nopol {{nopol}}'
        rendered = render_template(content, {'nama_wp': 'Anto', 'nopol': 'KH1234AA'})
        self.assertEqual(rendered, 'Yth, Anto Nopol KH1234AA')

    def test_no_placeholders_is_a_passthrough(self):
        content = 'Pesan biasa tanpa variabel.'
        self.assertEqual(render_template(content, {}), content)

    def test_non_string_variable_values_are_stringified(self):
        content = 'Total: {{amount}}'
        self.assertEqual(render_template(content, {'amount': 355000}), 'Total: 355000')

    def test_missing_variable_leaves_placeholder_untouched(self):
        # This never happens in practice (serializer validation guarantees
        # every recipient carries exactly the required set before a
        # campaign can even be created) — this only documents the
        # function's own behavior in isolation.
        content = 'Halo {{nama}}, nopol {{nopol}}'
        self.assertEqual(render_template(content, {'nama': 'Anto'}), 'Halo Anto, nopol {{nopol}}')
