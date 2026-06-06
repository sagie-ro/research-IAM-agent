from code_qa.languages import profile_for, supported_extensions

PY = b"""
class Base: ...
class Child(Base):
    def run(self):
        helper()
def helper(): ...
def main():
    Child().run()
if __name__ == "__main__":
    main()
"""

JAVA = b"""
package p;
import a.b.C;
public class S extends Base implements Runnable {
    public static void main(String[] a){ new Helper().go(); }
    void work(){ helper(); }
}
"""


def test_extensions_registered():
    assert {".py", ".java"} <= supported_extensions()


def test_python_symbols_and_edges():
    fp = profile_for("m.py").parse(PY, "m.py")
    kinds = {s.kind for s in fp.symbols}
    assert {"class", "function", "method"} <= kinds
    assert any(s.is_entry for s in fp.symbols)
    types = {e.type for e in fp.edges}
    assert "calls" in types and "extends" in types


def test_java_symbols_and_edges():
    fp = profile_for("S.java").parse(JAVA, "S.java")
    assert any(s.kind == "class" for s in fp.symbols)
    assert any(s.is_entry and s.name == "main" for s in fp.symbols)
    types = {e.type for e in fp.edges}
    assert {"calls", "extends", "implements", "imports"} <= types
