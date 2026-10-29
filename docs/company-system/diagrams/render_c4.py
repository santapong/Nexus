"""Render static C4 and action-lifecycle views with only the Python stdlib.

This file exceeds the size guideline to keep the four coordinated views and their
shared renderer together, so labels, boundaries and styling can be audited together.

Evidence: ../ARCHITECTURE.md, ../../../README.md, backend/nexus/company_app.py,
backend/nexus/execution/{dbos_queue,planning_worker,coding_worker}.py and
backend/nexus/core/llm/company_adapters.py. These are target views, not releases.
Run from any directory: python docs/company-system/diagrams/render_c4.py
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent


def text(x: int, y: int, value: str, cls: str = "body", anchor: str = "start") -> str:
    """Escape and position a single labeled SVG text element."""
    colors = {
        "body": "#c1d4d3",
        "tag": "#79d9c6",
        "subtitle": "#b5cbc9",
        "frame-label": "#a9c5c2",
        "foot": "#a9c0be",
        "eyebrow": "#76d5c3",
        "edge-label": "#d6e8e4",
    }
    return (
        f'<text x="{x}" y="{y}" class="{cls}" fill="{colors.get(cls, "#e9f4f3")}" '
        f'text-anchor="{anchor}">{escape(value)}</text>'
    )


def box(
    x: int,
    y: int,
    w: int,
    h: int,
    kind: str,
    title: str,
    lines: list[str],
    target: bool = False,
    label: str | None = None,
) -> str:
    """Render a labeled entity with an optional target-state outline."""
    dash = ' stroke-dasharray="8 6"' if target else ""
    colors = {
        "person": ("#173b46", "#60e2ca"),
        "system": ("#17382f", "#60e2ca"),
        "external": ("#243044", "#8093a6"),
        "container": ("#193344", "#61cbbd"),
        "component": ("#1c3442", "#61cbbd"),
        "data": ("#263548", "#8aa2b5"),
    }
    fill, stroke = colors[kind]
    result = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="15" class="{kind}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="2"{dash}/>'
    ]
    result += [text(x + 18, y + 27, (label or kind).upper().replace("-", " "), "tag")]
    result += [text(x + 18, y + 57, title, "box-title")]
    result += [text(x + 18, y + 84 + i * 22, line, "body") for i, line in enumerate(lines)]
    return "\n".join(result)


def edge(points: list[tuple[int, int]], label: str, lx: int, ly: int, target: bool = False) -> str:
    """Draw a directed connector with its semantic relationship label."""
    dash = ' stroke-dasharray="7 6"' if target else ""
    coords = " ".join(f"{x},{y}" for x, y in points)
    x1, y1 = points[-2]
    x2, y2 = points[-1]
    if x2 > x1:
        arrow = [(x2, y2), (x2 - 9, y2 - 5), (x2 - 9, y2 + 5)]
    elif x2 < x1:
        arrow = [(x2, y2), (x2 + 9, y2 - 5), (x2 + 9, y2 + 5)]
    elif y2 > y1:
        arrow = [(x2, y2), (x2 - 5, y2 - 9), (x2 + 5, y2 - 9)]
    else:
        arrow = [(x2, y2), (x2 - 5, y2 + 9), (x2 + 5, y2 + 9)]
    tip = " ".join(f"{x},{y}" for x, y in arrow)
    return (
        f'<polyline points="{coords}" fill="none" stroke="#80d8c7" stroke-width="2.3"{dash}/>'
        f'<polygon points="{tip}" fill="#80d8c7"/>\n' + text(lx, ly, label, "edge-label")
    )


def frame(x: int, y: int, w: int, h: int, label: str) -> str:
    """Draw a labeled logical or system boundary."""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="20" class="frame" '
        'fill="#122235" stroke="#496476" stroke-width="1.6" stroke-dasharray="7 7"/>\n'
        + text(x + 20, y + 30, label, "frame-label")
    )


def document(title: str, subtitle: str, content: str, desc: str) -> str:
    """Wrap authored diagram elements in an accessible standalone SVG."""
    escaped_title = escape(title)
    escaped_description = escape(desc)
    masthead = text(
        60,
        56,
        "NEXUS  /  SUPPORTING DYNAMIC VIEW"
        if title.startswith("04")
        else "NEXUS  /  C4 ARCHITECTURE",
        "eyebrow",
    )
    heading = text(60, 105, title, "heading")
    subtitle_line = text(60, 138, subtitle, "subtitle")
    body = content
    target_note = text(
        60,
        874,
        "TARGET VIEW  ·  Lines describe intended boundaries, not release acceptance.",
        "foot",
    )
    evidence_note = text(
        60, 900, "Evidence: docs/company-system/ARCHITECTURE.md and the Nexus task board.", "foot"
    )
    signature = text(1540, 900, "DRAVENIQ  /  NEXUS", "foot", "end")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" '
        'height="940" viewBox="0 0 1600 940" role="img" '
        'aria-labelledby="title description">\n<title id="title">'
        f"{escaped_title}"
        '</title><desc id="description">'
        f"{escaped_description}"
        "</desc>\n"
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#80d8c7"/></marker></defs>\n'
        "<style>\n"
        ".bg{fill:#0b1422} .frame{fill:#122235;stroke:#496476;"
        "stroke-width:1.6;stroke-dasharray:7 7}\n"
        ".person{fill:#173b46;stroke:#60e2ca;stroke-width:2} "
        ".system{fill:#17382f;stroke:#60e2ca;stroke-width:2}\n"
        ".external{fill:#243044;stroke:#8093a6;stroke-width:2} "
        ".container{fill:#193344;stroke:#61cbbd;stroke-width:2}\n"
        ".component{fill:#1c3442;stroke:#61cbbd;stroke-width:2} "
        ".data{fill:#263548;stroke:#8aa2b5;stroke-width:2}\n"
        ".edge{fill:none;stroke:#80d8c7;stroke-width:2.3;"
        "stroke-linejoin:round} text{font-family:Inter,Arial,sans-serif;"
        "fill:#e9f4f3}\n"
        ".heading{font-size:37px;font-weight:700} "
        ".subtitle{font-size:19px;fill:#b5cbc9} .tag{font-size:13px;"
        "font-weight:700;letter-spacing:1.5px;fill:#79d9c6}\n"
        ".box-title{font-size:22px;font-weight:700} .body{font-size:16px;"
        "fill:#c1d4d3} .edge-label{font-size:15px;fill:#d6e8e4;"
        "paint-order:stroke;stroke:#0b1422;stroke-width:6px;"
        "stroke-linejoin:round}\n"
        ".frame-label{font-size:16px;font-weight:700;fill:#a9c5c2;"
        "letter-spacing:.5px} .foot{font-size:15px;fill:#a9c0be} "
        ".eyebrow{font-size:15px;fill:#76d5c3;font-weight:700;"
        "letter-spacing:2px}\n"
        '</style><rect class="bg" width="1600" height="940" rx="18"/>\n'
        f"{masthead}"
        "\n"
        f"{heading}"
        "\n"
        f"{subtitle_line}"
        "\n"
        f"{body}"
        '\n<path d="M60 842H1540" stroke="#405a65" stroke-width="1"/>\n'
        f"{target_note}"
        "\n"
        f"{evidence_note}"
        "\n"
        f"{signature}"
        "\n</svg>"
    )


def context() -> str:
    """Draw the company system and its external actors."""
    edges = [
        edge([(400, 320), (560, 320)], "goals · approvals", 411, 305),
        edge([(560, 360), (400, 360)], "reports · decisions", 414, 390),
        edge([(400, 625), (470, 625), (470, 435), (560, 435)], "evidence · citations", 420, 600),
        edge([(1040, 320), (1200, 320)], "model request", 1060, 305, True),
        edge([(1200, 360), (1040, 360)], "result · usage", 1060, 390, True),
        edge(
            [(1040, 435), (1120, 435), (1120, 625), (1200, 625)],
            "owner notification",
            1048,
            535,
            True,
        ),
    ]
    boxes = [
        box(
            80,
            280,
            320,
            130,
            "person",
            "Company owner",
            ["Sets direction and reviews", "proposals, outcomes and cost."],
        ),
        box(
            560,
            270,
            480,
            200,
            "system",
            "Nexus",
            [
                "DravenIQ company brain and action harness",
                "Evidence → supervised decisions → work",
                "Unknown outcomes remain visible.",
            ],
        ),
        box(
            80,
            570,
            320,
            130,
            "external",
            "Company sources",
            ["Repositories and documents", "admitted with access controls."],
        ),
        box(
            1200,
            280,
            320,
            130,
            "external",
            "Model providers",
            ["Registered adapters; live", "qualification remains open."],
            True,
        ),
        box(
            1200,
            570,
            320,
            130,
            "external",
            "Owner email",
            ["Delivery is optional and", "not yet qualified."],
            True,
        ),
    ]
    return document(
        "01  System context",
        "Who uses Nexus and which external systems it is intended to reach.",
        "\n".join(edges + boxes),
        (
            "Owner interacts with Nexus. Company sources provide evidence. Nex"
            "us may use registered model providers and send owner email; live "
            "qualification remains open."
        ),
    )


def containers() -> str:
    """Draw the target runtime and storage boundaries."""
    layers = [frame(55, 205, 1110, 550, "NEXUS SYSTEM  ·  runtime and storage boundaries")]
    edges = [
        edge([(310, 340), (400, 340)], "HTTP", 333, 325),
        edge([(645, 340), (790, 340)], "DBOS queue", 667, 325),
        edge([(525, 400), (525, 495), (365, 495), (365, 570)], "read · commit", 370, 480),
        edge([(915, 400), (915, 480), (675, 480), (675, 570)], "persist references", 696, 463),
        edge([(810, 400), (810, 720), (365, 720), (365, 695)], "checkpoints · ledger", 490, 742),
        edge([(1040, 320), (1220, 320)], "guarded SDK calls", 1050, 304, True),
        edge([(1040, 365), (1115, 365), (1115, 570)], "bounded build", 1052, 500, True),
        edge([(1040, 385), (1185, 385), (1185, 640), (1220, 640)], "delivery", 1220, 550, True),
    ]
    boxes = [
        box(75, 275, 235, 125, "container", "Dashboard", ["React + Vite", "Owner interface"]),
        box(
            400,
            275,
            245,
            125,
            "container",
            "Company API",
            ["Litestar; opt-in", "No worker at startup"],
        ),
        box(
            790,
            275,
            250,
            125,
            "container",
            "DBOS workers",
            ["Explicitly configured", "Durable segments"],
        ),
        box(
            240,
            570,
            250,
            125,
            "data",
            "PostgreSQL",
            ["Work · approvals · ledger", "Transaction + enqueue"],
        ),
        box(
            550,
            570,
            250,
            125,
            "data",
            "Artifact storage",
            ["Bounded bytes and", "protected references"],
        ),
        box(
            865,
            570,
            250,
            125,
            "container",
            "Build + verify",
            ["Separate bounded jobs", "ARM64 unqualified"],
            True,
        ),
        box(
            1220,
            275,
            310,
            125,
            "external",
            "Model providers",
            ["OpenAI / Google adapters", "Live calls unqualified"],
            True,
        ),
        box(
            1220,
            575,
            310,
            125,
            "external",
            "Owner email",
            ["Optional delivery target", "External delivery unqualified"],
            True,
        ),
    ]
    return document(
        "02  Containers",
        (
            "Runtime boundaries for the supervised target; dashed boxes and pa"
            "ths still need qualification."
        ),
        "\n".join(layers + edges + boxes),
        (
            "Dashboard calls the opt-in company API. Separately configured DBO"
            "S workers use PostgreSQL, protected artifacts and guarded models."
            " Builder isolation and owner email are unqualified target paths."
        ),
    )


def components() -> str:
    """Draw the selected company API components."""
    layers = [
        frame(
            55,
            205,
            1490,
            530,
            "COMPANY API  ·  selected components; effect checks also run in workers",
        )
    ]
    edges = [
        edge([(305, 335), (390, 335)], "scope", 329, 320),
        edge([(655, 335), (735, 335)], "evidence", 667, 320),
        edge([(1005, 335), (1090, 335)], "propose", 1020, 320),
        edge([(520, 405), (520, 540)], "ACL · provenance", 530, 480),
        edge([(865, 405), (865, 540)], "goals · plans", 875, 480),
        edge([(1230, 405), (1230, 540)], "recheck · persist", 1240, 480),
    ]
    boxes = [
        box(
            75,
            270,
            230,
            135,
            "component",
            "Identity & scope",
            ["Signed identity and current", "directory membership"],
        ),
        box(
            390,
            270,
            265,
            135,
            "component",
            "Company Brain",
            ["Sources · citations · ontology", "Access checked before bytes"],
        ),
        box(
            735,
            270,
            270,
            135,
            "component",
            "Management",
            ["Goals · charters · plans", "Owner decisions"],
        ),
        box(
            1090,
            270,
            300,
            135,
            "component",
            "Action Harness",
            ["Authority · limits · intent", "Unknown effects reconcile"],
        ),
        box(
            390, 540, 265, 125, "data", "Protected sources", ["Revision and evidence", "references"]
        ),
        box(735, 540, 270, 125, "data", "Management records", ["Company state", "and decisions"]),
        box(
            1090,
            540,
            300,
            125,
            "data",
            "Journal & execution",
            ["Costs · receipts · fences", "DBOS dispatch identity"],
        ),
    ]
    return document(
        "03  Components",
        (
            "Responsibility boundaries in the company code; knowledge and mode"
            "l output do not grant authority."
        ),
        "\n".join(layers + edges + boxes),
        (
            "Identity scopes company access, Brain supplies permission-checked"
            " evidence, Management proposes work, and the Action Harness indep"
            "endently enforces action authority, cost, durable intent and reco"
            "very."
        ),
    )


def lifecycle() -> str:
    """Draw the supervised action and reconciliation flow."""
    edges = [
        edge([(300, 350), (365, 350)], "review", 307, 335),
        edge([(610, 350), (675, 350)], "approve", 615, 335),
        edge([(920, 350), (985, 350)], "queue", 935, 335),
        edge([(1110, 405), (1110, 555)], "receipt", 1122, 487),
        edge(
            [(985, 365), (950, 365), (950, 520), (800, 520), (800, 555)],
            "uncertain outcome",
            805,
            503,
        ),
        edge([(925, 620), (985, 620)], "reconciled", 895, 540),
        edge([(1235, 620), (1290, 620)], "passes", 1240, 603),
    ]
    boxes = [
        box(
            55,
            275,
            245,
            130,
            "component",
            "Proposed",
            ["Exact action and", "evidence recorded"],
            label="state",
        ),
        box(
            365,
            275,
            245,
            130,
            "person",
            "Owner decision",
            ["Approve exact proposal", "or reject / let expire"],
            label="decision",
        ),
        box(
            675,
            275,
            245,
            130,
            "component",
            "Authorized",
            ["Recheck policy and scope", "Reserve cost; enqueue"],
            label="state",
        ),
        box(
            985,
            275,
            250,
            130,
            "component",
            "Executing",
            ["Persist intent before", "a one-time effect"],
            label="state",
        ),
        box(
            675,
            555,
            250,
            130,
            "external",
            "Outcome unknown",
            ["Keep hold; reconcile", "No blind retry"],
            label="state",
        ),
        box(
            985,
            555,
            250,
            130,
            "component",
            "Verifying",
            ["Independent check", "Inconclusive remains open"],
            label="state",
        ),
        box(
            1290,
            555,
            245,
            130,
            "system",
            "Completed",
            ["Evidence-backed", "acceptance recorded"],
            label="state",
        ),
    ]
    return document(
        "04  Action lifecycle",
        "Approval, dispatch and reconciliation are distinct; shown as intended behavior.",
        "\n".join(edges + boxes),
        (
            "A proposed action receives an owner decision; authorized work res"
            "erves its cost and executes. Unknown effects are reconciled, whil"
            "e independent evidence is required before completion."
        ),
    )


def main() -> None:
    """Write each checked-in SVG in the same directory as this source."""
    for filename, render in (
        ("c4-system-context.svg", context),
        ("c4-containers.svg", containers),
        ("c4-components.svg", components),
        ("action-lifecycle.svg", lifecycle),
    ):
        (OUT / filename).write_text(render() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
