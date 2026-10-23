"""Static checks of public/index.html: what would otherwise only show up as a broken button in the browser."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "index.html")
HTML = open(PAGE, encoding="utf-8").read()
JS = re.search(r"<script>(.*?)</script>", HTML, re.S).group(1)


class Page(unittest.TestCase):
    def test_javascript_parses(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(JS)
        try:
            r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            os.unlink(f.name)

    def test_every_element_id_the_script_uses_exists(self):
        used = set(re.findall(r"getElementById\('([^']+)'\)", JS))
        present = set(re.findall(r'id="([^"]+)"', HTML))
        self.assertEqual(used - present, set())

    def test_every_onclick_has_a_function(self):
        fns = set(re.findall(r"function (\w+)\(", JS))
        self.assertEqual(set(re.findall(r'onclick="(\w+)\(', HTML)) - fns, set())

    def test_no_external_requests_and_no_dead_features(self):
        self.assertEqual(re.findall(r"""(?:src|href|action)=["']https?://""", HTML), [])
        self.assertEqual(re.findall(r"@import|url\(https?:", HTML), [])
        for gone in ("openrouter", "fonts.googleapis", "api/admin/knowledge", "customText", "monkAddon"):
            self.assertNotIn(gone, HTML)

    def test_data_from_the_server_is_escaped_before_innerhtml(self):
        self.assertIn("function esc(", JS)
        for needle in ("${esc(u.username)}", "${esc(u.display_name)}", "esc(p.unparsed)", "esc(u.text)", "esc(n.text)"):
            self.assertIn(needle, JS, needle)
        self.assertNotIn("${u.username}", JS.replace("resetPin(${u.id},'${u.username}')", ""))      # only the validated username in onclick

    def test_html_tags_are_balanced(self):
        """A removed block that takes a closing tag with it breaks the whole layout silently (seen once already)."""
        from html.parser import HTMLParser
        void = {"meta", "link", "input", "br", "hr", "img"}
        stack, problems = [], []

        class P(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag not in void: stack.append((tag, self.getpos()[0]))
            def handle_endtag(self, tag):
                if tag in void: return
                if not stack or stack[-1][0] != tag:
                    problems.append(f"</{tag}> at line {self.getpos()[0]} but open is {stack[-1] if stack else None}")
                    if tag in [t for t, _ in stack]:
                        while stack and stack.pop()[0] != tag: pass
                else:
                    stack.pop()
        P().feed(HTML)
        self.assertEqual(problems, [])
        self.assertEqual(stack, [])

    def test_layout_blocks_are_where_they_belong(self):
        grid = HTML[HTML.index('<div class="pattern-grid"'):HTML.index("<!-- Monk Toggle -->")]
        self.assertEqual(grid.count("<div"), grid.count("</div>"), "pattern-grid must be closed before the monk toggle")
        self.assertLess(HTML.index('id="monkToggle"'), HTML.index('id="labValues"'))

    def test_every_admin_tool_is_inside_the_single_settings_menu(self):
        menu = re.search(r'<div class="menu-list" id="adminMenuList">(.*?)</div>\s*</div>', HTML, re.S).group(1)
        tools = ("rulesBtn", "targetsBtn", "goldenBtn", "signBtn", "learnBtn", "statsBtn", "adminBtn")
        for t in tools:
            self.assertIn(f'id="{t}"', menu, t)
        header = HTML[HTML.index('<div class="header-right">'):HTML.index('<!-- ===== RULES MODAL')]
        self.assertEqual(len(re.findall(r'class="hdr-btn"', header.replace(menu, ""))), 2)                  # only the menu button and logout stay on the bar
        self.assertIn('onclick="doLogout()"', header.replace(menu, ""))
        self.assertIn("menuWrap').style.display = 'block'", JS); self.assertIn("function toggleMenu(", JS); self.assertIn("Escape", JS)

    def test_draft_warning_is_wired(self):
        self.assertIn("draftWarn", HTML); self.assertIn("DRAFT", JS)


if __name__ == "__main__":
    unittest.main()
