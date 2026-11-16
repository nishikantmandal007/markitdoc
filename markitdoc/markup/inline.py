import re
from dataclasses import dataclass
from markdown_it import MarkdownIt
from mdit_py_plugins.attrs import attrs_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.subscript import sub_plugin
from mdit_py_plugins.superscript import superscript_plugin
from mdit_py_plugins.tasklists import tasklists_plugin


parser = (MarkdownIt("commonmark").enable(["table", "strikethrough"]).disable(["html_block", "html_inline"])
          .use(footnote_plugin).use(tasklists_plugin).use(deflist_plugin).use(attrs_plugin, spans=True)
          .use(sub_plugin).use(superscript_plugin).use(dollarmath_plugin, allow_space=False, allow_digits=False, double_inline=True))
tex_symbols = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "theta": "θ", "lambda": "λ", "mu": "μ",
               "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "phi": "φ", "omega": "ω", "Delta": "Δ", "Sigma": "Σ", "Omega": "Ω",
               "cdot": "·", "times": "×", "div": "÷", "pm": "±", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠",
               "approx": "≈", "infty": "∞", "sum": "Σ", "prod": "Π", "int": "∫", "rightarrow": "→", "to": "→", "leftarrow": "←",
               "in": "∈", "partial": "∂", "nabla": "∇", "sqrt": "√", "ldots": "…", "dots": "…", "cdots": "⋯",
               "varepsilon": "ε", "vartheta": "ϑ", "varphi": "φ", "eta": "η", "kappa": "κ", "nu": "ν", "xi": "ξ", "chi": "χ",
               "psi": "ψ", "zeta": "ζ", "Gamma": "Γ", "Theta": "Θ", "Lambda": "Λ", "Pi": "Π", "Phi": "Φ", "Psi": "Ψ",
               "oplus": "⊕", "odot": "⊙", "otimes": "⊗", "gg": "≫", "ll": "≪", "sim": "∼", "simeq": "≃", "equiv": "≡",
               "propto": "∝", "circ": "∘", "prime": "′", "degree": "°", "perp": "⊥", "parallel": "∥", "forall": "∀",
               "exists": "∃", "Rightarrow": "⇒", "Leftrightarrow": "⇔", "mapsto": "↦", "hbar": "ħ", "ell": "ℓ"}
tex_text_commands = ("text", "mathrm", "textrm", "mathit", "textit", "operatorname", "mathsf", "mathcal", "boldsymbol",
                     "mathbf", "textbf")
tex_accents = {"dot": "\u0307", "ddot": "\u0308", "hat": "\u0302", "bar": "\u0304", "overline": "\u0304"}
bold_open, bold_close = "\u0001", "\u0002"
subscripts = str.maketrans("0123456789+-=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")
superscripts = str.maketrans("0123456789+-=()abcdefghijklmnoprstuvwxyz", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ")
anchor = re.compile(r"\s*\{#([\w-]+)\}\s*$")
superscript_digits = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


@dataclass(frozen=True)
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    role: str = ""
    script: str = ""
    link: str = ""
    highlight: bool = False


span_roles = {"accent": "mood", "second": "second", "muted": "muted", "danger": "danger", "success": "success", "highlight": "ink"}


def inline_runs(token, targets=frozenset()) -> list[Run]:
    runs, state, spans, link = [], {"bold": 0, "italic": 0, "strike": 0}, [], ""
    script = ""

    def add(text, **extra):
        if text:
            runs.append(Run(text, bold=state["bold"] > 0 or extra.get("bold", False), italic=state["italic"] > 0,
                            strike=state["strike"] > 0, underline=any(span[0] for span in spans),
                            role=next((span[1] for span in reversed(spans) if span[1]), ""), script=extra.get("script", script),
                            link=link, highlight=any(span[2] for span in spans)))

    for child in token.children or []:
        kind = child.type
        if kind in ("text", "code_inline"):
            add(child.content)
        elif kind in ("strong_open", "em_open", "s_open"):
            state[{"strong_open": "bold", "em_open": "italic", "s_open": "strike"}[kind]] += 1
        elif kind in ("strong_close", "em_close", "s_close"):
            name = {"strong_close": "bold", "em_close": "italic", "s_close": "strike"}[kind]
            state[name] = max(0, state[name] - 1)
        elif kind in ("sub_open", "sup_open"):
            script = "SUB" if kind == "sub_open" else "SUP"
        elif kind in ("sub_close", "sup_close"):
            script = ""
        elif kind == "softbreak":
            add(" ")
        elif kind == "hardbreak":
            add("\n")
        elif kind == "link_open":
            target = str(child.attrs.get("href") or "")
            link = target if target.startswith(("http://", "https://", "mailto:")) or target[1:] in targets else ""
        elif kind == "link_close":
            link = ""
        elif kind in ("math_inline", "math_inline_double"):
            for index, piece in enumerate(re.split(f"[{bold_open}{bold_close}]", inline_maths(child.content))):
                add(piece, bold=index % 2 == 1)
        elif kind == "footnote_ref":
            add(str(child.meta["id"] + 1).translate(superscripts))
        elif kind == "html_inline" and "checkbox" in child.content:
            add("☑ " if "checked" in child.content else "☐ ")
        elif kind == "span_open":
            classes = str(child.attrs.get("class", "")).split()
            spans.append(("underline" in classes, next((span_roles[name] for name in classes if name in span_roles), ""),
                          "highlight" in classes))
        elif kind == "span_close" and spans:
            spans.pop()
    return runs


def inline_maths(tex):
    text = re.sub(r"\\(left|right|big|Big|bigg|Bigg)\b", "", tex)
    text = re.sub(r"\\[,;:! ]|\\q?quad\b", " ", text)
    text = re.sub(r"\\(" + "|".join(tex_text_commands) + r")\{([^{}]*)\}",
                  lambda match: (bold_open + match.group(2) + bold_close) if match.group(1) in ("mathbf", "textbf", "boldsymbol")
                  else match.group(2), text)
    text = re.sub(r"\\vec\{([^{}]*)\}|\\vec\s*(\w)", lambda match: bold_open + (match.group(1) or match.group(2)) + bold_close, text)
    text = re.sub(r"\\(" + "|".join(tex_accents) + r")\{(\w)\}|\\(" + "|".join(tex_accents) + r")\s*(\w)",
                  lambda match: (match.group(2) or match.group(4)) + tex_accents[match.group(1) or match.group(3)], text)
    text = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", text)
    text = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", text)
    text = re.sub(r"\\([A-Za-z]+)", lambda match: tex_symbols.get(match.group(1), match.group(1)), text)
    text = re.sub(r"\^\{([^{}]*)\}|\^([^\s{}])", lambda match: (match.group(1) or match.group(2)).translate(superscripts), text)
    text = re.sub(r"_\{([^{}]*)\}|_([^\s{}])", lambda match: (match.group(1) or match.group(2)).translate(subscripts), text)
    text = re.sub(r"√\((\w)\)", r"√\1", text.replace("{", "").replace("}", ""))
    text = re.sub(r"\(([^\s()+\-*/=]+)\)/", r"\1/", text)
    text = re.sub(r"/\(([^\s()+\-*/=]+)\)", r"/\1", text)
    return re.sub(r" {2,}", " ", text).strip()
