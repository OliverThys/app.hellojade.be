"""
Service de génération de rapports PDF pour HelloJADE — Epicura
Structure clinique : fiche patient, résumé déterministe, réponses structurées, annexe transcription.
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    HRFlowable, KeepTogether, PageBreak, Flowable
)
from reportlab.pdfgen import canvas as pdfcanvas

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Palette ───────────────────────────────────────────────────────────────────
SLATE_950   = colors.HexColor('#020617')
SLATE_900   = colors.HexColor('#0F172A')
SLATE_800   = colors.HexColor('#1E293B')
SLATE_700   = colors.HexColor('#334155')
SLATE_600   = colors.HexColor('#475569')
SLATE_500   = colors.HexColor('#64748B')
SLATE_400   = colors.HexColor('#94A3B8')
SLATE_200   = colors.HexColor('#E2E8F0')
SLATE_100   = colors.HexColor('#F1F5F9')
SLATE_50    = colors.HexColor('#F8FAFC')
WHITE       = colors.white

EMERALD_900 = colors.HexColor('#064E3B')
EMERALD_700 = colors.HexColor('#047857')
EMERALD_600 = colors.HexColor('#059669')
EMERALD_500 = colors.HexColor('#10B981')
EMERALD_400 = colors.HexColor('#34D399')
EMERALD_200 = colors.HexColor('#A7F3D0')
EMERALD_100 = colors.HexColor('#D1FAE5')
EMERALD_50  = colors.HexColor('#ECFDF5')

RED_900     = colors.HexColor('#7F1D1D')
RED_MAIN    = colors.HexColor('#B91C1C')
RED_600     = colors.HexColor('#DC2626')
RED_LIGHT   = colors.HexColor('#FEE2E2')
RED_50      = colors.HexColor('#FFF5F5')

ORANGE_MAIN = colors.HexColor('#C2410C')
ORANGE_600  = colors.HexColor('#EA580C')
ORANGE_LIGHT= colors.HexColor('#FFEDD5')
ORANGE_50   = colors.HexColor('#FFF7ED')

YELLOW_MAIN = colors.HexColor('#A16207')
YELLOW_LIGHT= colors.HexColor('#FEF9C3')

GREEN_MAIN  = colors.HexColor('#15803D')
GREEN_LIGHT = colors.HexColor('#DCFCE7')

# Rétrocompat interne
GRAY_900 = SLATE_900
GRAY_700 = SLATE_700
GRAY_500 = SLATE_500
GRAY_200 = SLATE_200
GRAY_100 = SLATE_100
BLUE_LIGHT = EMERALD_50
BLUE_MAIN  = EMERALD_600

LOGO_PATH = Path(__file__).parent.parent / "assets" / "hellojade_logo.png"

MAX_CALL_ATTEMPTS = 3


def _hex(c) -> str:
    """Retourne '#RRGGBB' depuis un objet color ReportLab."""
    return '#%02x%02x%02x' % (int(c.red * 255 + 0.5), int(c.green * 255 + 0.5), int(c.blue * 255 + 0.5))


# ── Statut appel ──────────────────────────────────────────────────────────────
def _get_display_status(call_data: Dict[str, Any]) -> Tuple[str, Any, Any, Any]:
    """Retourne (label, border_color, bg_color, text_color) selon le statut de l'appel."""
    status   = call_data.get("status", "")
    attempts = int(call_data.get("attempts") or 0)

    if status == "completed":
        return "Finalisé", EMERALD_600, EMERALD_50, EMERALD_700
    if status in ("failed", "no_answer", "busy"):
        if attempts >= MAX_CALL_ATTEMPTS:
            return "Échec", RED_MAIN, RED_LIGHT, RED_900
        return "À rappeler", ORANGE_600, ORANGE_50, ORANGE_MAIN
    if status == "cancelled":
        return "Annulé", SLATE_500, SLATE_100, SLATE_700
    if status == "in_progress":
        return "En cours", EMERALD_500, EMERALD_50, EMERALD_700
    return status.replace("_", " ").title(), SLATE_500, SLATE_100, SLATE_700


# Libellés humains pour les alert_reason connus
_ALERT_REASON_LABELS: Dict[str, str] = {
    "Q1_douleur":               "Douleur signalée",
    "Q1a_score_douleur":        "Score de douleur élevé",
    "Q1b_empeche_dormir":       "Douleur empêchant le sommeil/déplacement",
    "Q1c_intolerable":          "Douleur intolérable ou aggravée",
    "Q1d_antidouleurs":         "Antidouleurs insuffisamment efficaces",
    "Q2_alimentation":          "Difficultés alimentaires",
    "Q3_nausees":               "Nausées ou vomissements",
    "Q3a_nausees_persistantes":  "Nausées persistantes tout au long de la journée",
    "Q3b_vomissements_repetes": "Vomissements répétés",
    "Q4_pansement":             "Pansement souillé ou mouillé",
    "Q5_medecin":               "Consultation médicale depuis la sortie",
    "Q6_autres_symptomes":      "Autres symptômes préoccupants signalés",
    "Q6a_symptome_detail":      "Symptôme préoccupant détaillé",
    "Q7_parler_equipe":         "Patient souhaite parler à l'équipe médicale",
}


# ── Cas déterministe ──────────────────────────────────────────────────────────
def _determine_case(
    call_data:     Dict[str, Any],
    analysis_data: Optional[Dict[str, Any]],
    call_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[int, List[str]]:
    """
    Retourne (cas, raisons) de façon déterministe :
      1 → patient RAS, pas de signes inquiétants
      2 → patient a nécessité un suivi ou est à rappeler
      3 → échec total (3 tentatives sans réponse)
    """
    status   = call_data.get("status", "")
    attempts = int(call_data.get("attempts") or 0)

    # Cas 3 : échec total
    if status in ("failed", "no_answer", "busy", "cancelled") and attempts >= MAX_CALL_ATTEMPTS:
        return 3, []

    # Cas 2a : appel non finalisé, à retenter
    if status in ("failed", "no_answer", "busy"):
        return 2, ["Le patient n'a pas répondu — un rappel est programmé."]

    # Cas 2b : alerte déclenchée pendant l'appel (source principale)
    if call_metadata and call_metadata.get("alert_triggered"):
        alert_reason = str(call_metadata.get("alert_reason") or "")
        label = _ALERT_REASON_LABELS.get(alert_reason, alert_reason.replace("_", " ") if alert_reason else "Alerte clinique")
        symptom = call_metadata.get("alert_symptom_detail")
        reason_text = label
        if symptom:
            reason_text += f" : « {symptom} »"
        return 2, [reason_text]

    # Cas 2c : alertes cliniques dans analysis_data
    reasons: List[str] = []
    if analysis_data:
        alerts = [a for a in (analysis_data.get("alerts") or [])
                  if a.get("severity") in ("urgent", "high")]
        risk_score = int(analysis_data.get("risk_score") or 0)
        for a in alerts:
            msg = a.get("message", "")
            if msg:
                reasons.append(msg)
        if risk_score >= 6 and not reasons:
            reasons.append(f"Score de risque clinique élevé ({risk_score}/10).")
        if reasons:
            return 2, reasons

    # Cas 1 : RAS
    return 1, []


# ── Formatage réponse question ─────────────────────────────────────────────────
def _format_answer_human(ans: Dict[str, Any]) -> str:
    """Transforme une réponse parsée en phrase lisible par un clinicien."""
    parsed = ans.get("parsed") if isinstance(ans.get("parsed"), dict) else {}

    if parsed.get("skipped"):
        return "Pas de réponse exploitable"
    if parsed.get("out_of_scope"):
        return "Question hors périmètre"

    answer = parsed.get("answer")
    qid    = str(ans.get("question_id") or "").lower()

    if answer is None:
        raw = str(ans.get("transcript") or "").strip()
        return raw[:180] if raw else "—"

    if isinstance(answer, bool):
        return "Oui" if answer else "Non"

    if isinstance(answer, (int, float)):
        if any(k in qid for k in ("douleur", "pain", "score")):
            return f"Score de douleur : {int(answer)}/10"
        if "moral" in qid:
            return f"État moral : {int(answer)}/5"
        if any(k in qid for k in ("fievre", "temperature", "temp")):
            return f"Température : {answer}°C"
        return f"Valeur : {answer}"

    return str(answer)[:200]


def _answer_has_alert(
    ans:           Dict[str, Any],
    analysis_data: Optional[Dict[str, Any]],
    call_metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Détermine si une réponse individuelle a déclenché une alerte."""
    qid = str(ans.get("question_id") or "").lower()

    # 1. Champ explicite dans la réponse
    if ans.get("alert") is True or ans.get("alert_triggered") is True:
        return True

    # 2. alert_reason dans call_metadata — source principale de vérité
    if call_metadata and call_metadata.get("alert_triggered") and qid:
        alert_reason = str(call_metadata.get("alert_reason") or "").lower()
        if alert_reason and qid == alert_reason:
            return True

    # 3. Correspondance dans analysis_data.alerts
    if analysis_data and qid:
        for alert in (analysis_data.get("alerts") or []):
            if qid in str(alert.get("question_id") or "").lower():
                return True

    # 4. Heuristiques cliniques sur la réponse parsée
    parsed = ans.get("parsed") if isinstance(ans.get("parsed"), dict) else {}
    if parsed.get("skipped") or parsed.get("out_of_scope"):
        return False
    answer = parsed.get("answer")
    if answer is None or answer == "":
        return False

    def _is_yes(v) -> bool:
        return v in (True, "oui", "yes", 1, "1", "true")

    def _is_no(v) -> bool:
        return v in (False, "non", "no", 0, "0", "false")

    # Douleur score ≥ 7
    if "score_douleur" in qid and isinstance(answer, (int, float)) and float(answer) >= 7:
        return True
    # Douleur empêche de dormir/se déplacer
    if "empeche_dormir" in qid and _is_yes(answer):
        return True
    # Douleur intolérable ou aggravée
    if "intolerable" in qid and _is_yes(answer):
        return True
    # Antidouleurs pas du tout efficaces
    if "antidouleurs" in qid and isinstance(answer, str) and "pas du tout" in answer.lower():
        return True
    # Alimentation difficile
    if "alimentation" in qid and _is_no(answer):
        return True
    # Nausées persistantes
    if "nausees_persistantes" in qid and _is_yes(answer):
        return True
    # Vomissements répétés
    if "vomissements_repetes" in qid and _is_yes(answer):
        return True
    # Autres symptômes préoccupants
    if "autres_symptomes" in qid and _is_yes(answer):
        return True
    # Souhaite parler à l'équipe médicale
    if "parler_equipe" in qid and _is_yes(answer):
        return True

    return False


# ── Flowables ────────────────────────────────────────────────────────────────

class HeaderBanner(Flowable):
    """Bandeau en-tête : fond slate, accent émeraude, logo + titre."""
    def __init__(self, width: float, logo_path: Optional[Path] = None):
        Flowable.__init__(self)
        self.banner_width  = width
        self.banner_height = 2.8 * cm
        self.logo_path     = logo_path
        self.width         = width
        self.height        = self.banner_height

    def draw(self):
        c = self.canv
        bw, bh = self.banner_width, self.banner_height

        # Fond principal
        c.setFillColor(SLATE_900)
        c.roundRect(0, 0, bw, bh, 6, fill=1, stroke=0)

        # Ligne émeraude basse
        c.setFillColor(EMERALD_600)
        c.rect(0, 0, bw, 0.2 * cm, fill=1, stroke=0)

        # Barre verticale gauche
        c.setFillColor(EMERALD_500)
        c.roundRect(0, 0.2 * cm, 0.13 * cm, bh - 0.2 * cm, 2, fill=1, stroke=0)

        # Logo
        logo_x = 0.5 * cm
        if self.logo_path and Path(self.logo_path).exists():
            try:
                logo_h = 1.5 * cm
                logo_w = logo_h * 3.4
                c.drawImage(
                    str(self.logo_path),
                    logo_x, (bh - logo_h) / 2,
                    width=logo_w, height=logo_h,
                    preserveAspectRatio=True, mask='auto',
                )
                logo_x += logo_w + 0.4 * cm
            except Exception:
                pass

        # Titre
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(logo_x, bh / 2 + 0.28 * cm, "Rapport de suivi post-hospitalisation")
        c.setFont("Helvetica", 8)
        c.setFillColor(EMERALD_200)
        c.drawString(logo_x, bh / 2 - 0.22 * cm, "Appel automatisé  ·  HelloJADE  ·  Epicura")

        # Badge ORU/PDF
        badge_w, badge_h = 1.8 * cm, 0.76 * cm
        bx = bw - badge_w - 0.35 * cm
        by = (bh - badge_h) / 2
        c.setFillColor(SLATE_800)
        c.roundRect(bx, by, badge_w, badge_h, 4, fill=1, stroke=0)
        c.setFillColor(EMERALD_400)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(bx + badge_w / 2, by + badge_h / 2 - 0.08 * cm, "ORU / PDF")


class SummaryBox(Flowable):
    """Encadré résumé déterministe : cas 1 (vert), 2 (orange), 3 (gris)."""
    def __init__(self, cas: int, reasons: List[str], width: float, call_data: Dict[str, Any]):
        Flowable.__init__(self)
        self.cas       = cas
        self.reasons   = reasons
        self.width     = width
        self.call_data = call_data

        # Palette selon cas
        if cas == 1:
            self.border_color = EMERALD_600
            self.bg_color     = EMERALD_50
            self.icon         = "✓"
            self.icon_color   = EMERALD_700
            self.title        = "Aucun signe inquiétant détecté"
            self.body         = (
                "Le patient ne présente pas de signes cliniques nécessitant une intervention immédiate. "
                "Toutes les réponses se situent en dessous des seuils d'alerte définis."
            )
        elif cas == 2:
            self.border_color = ORANGE_600
            self.bg_color     = ORANGE_50
            self.icon         = "!"
            self.icon_color   = ORANGE_MAIN
            self.title        = "Suivi clinique requis"
            body_parts = ["Le patient a nécessité un suivi ou est à rappeler."]
            if reasons:
                body_parts.append("Motif(s) : " + " — ".join(reasons))
            self.body = " ".join(body_parts)
        else:
            self.border_color = SLATE_500
            self.bg_color     = SLATE_100
            self.icon         = "✗"
            self.icon_color   = SLATE_600
            self.title        = "Échec de l'appel — patient non joint"
            attempts = int(call_data.get("attempts") or 0)
            self.body         = (
                f"Le patient n'a pas pu être entendu après {attempts} tentative(s). "
                "Aucune donnée clinique n'a pu être collectée. Un suivi manuel est recommandé."
            )

        # Hauteur dynamique : on estime selon longueur du body
        lines = max(2, len(self.body) // 80 + 1)
        self.height = (1.2 + lines * 0.45) * cm

    def draw(self):
        c = self.canv
        w, h = self.width, self.height

        # Fond
        c.setFillColor(self.bg_color)
        c.roundRect(0, 0, w, h, 5, fill=1, stroke=0)

        # Bordure complète fine
        c.setStrokeColor(self.border_color)
        c.setLineWidth(1.0)
        c.roundRect(0, 0, w, h, 5, fill=0, stroke=1)

        # Barre gauche épaisse
        c.setFillColor(self.border_color)
        c.roundRect(0, 0, 0.28 * cm, h, 4, fill=1, stroke=0)

        # Icône
        icon_cx = 0.28 * cm + 0.65 * cm
        c.setFillColor(self.icon_color)
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(icon_cx, h / 2 - 0.25 * cm, self.icon)

        # Texte
        tx = icon_cx + 0.65 * cm
        c.setFillColor(SLATE_900)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(tx, h - 0.55 * cm, self.title)

        c.setFillColor(SLATE_700)
        c.setFont("Helvetica", 8.5)
        # Word-wrap manuel
        words = self.body.split()
        line, lines_drawn = "", []
        max_w = w - tx - 0.3 * cm
        for word in words:
            test = (line + " " + word).strip()
            if c.stringWidth(test, "Helvetica", 8.5) <= max_w:
                line = test
            else:
                lines_drawn.append(line)
                line = word
        if line:
            lines_drawn.append(line)

        y = h - 1.05 * cm
        for ln in lines_drawn:
            if y < 0.15 * cm:
                break
            c.drawString(tx, y, ln)
            y -= 0.42 * cm


class RiskBadge(Flowable):
    """Score de risque : badge numérique + jauge."""
    def __init__(self, score: int, width: float = 17 * cm):
        Flowable.__init__(self)
        self.score  = score
        self.width  = width
        self.height = 1.7 * cm

    def draw(self):
        c    = self.canv
        score = self.score or 0

        if score >= 9:
            label, bg, fg = "Critique", RED_LIGHT, RED_MAIN
        elif score >= 7:
            label, bg, fg = "Élevé", ORANGE_LIGHT, ORANGE_MAIN
        elif score >= 4:
            label, bg, fg = "Modéré", YELLOW_LIGHT, YELLOW_MAIN
        else:
            label, bg, fg = "Faible", GREEN_LIGHT, GREEN_MAIN

        c.setFillColor(SLATE_50)
        c.setStrokeColor(SLATE_200)
        c.setLineWidth(0.75)
        c.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=1)

        bw, bh = 1.75 * cm, 1.12 * cm
        by = (self.height - bh) / 2
        c.setFillColor(WHITE)
        c.setStrokeColor(fg)
        c.setLineWidth(1)
        c.roundRect(0.4 * cm, by, bw, bh, 3, fill=1, stroke=1)
        c.setFillColor(fg)
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(0.4 * cm + bw / 2, by + bh / 2 - 0.18 * cm, f"{score}")
        c.setFont("Helvetica", 6.5)
        c.setFillColor(SLATE_600)
        c.drawCentredString(0.4 * cm + bw / 2, by + 0.14 * cm, "/ 10")

        bar_x = 2.45 * cm
        bar_w = self.width - bar_x - 0.45 * cm
        bar_y = self.height / 2 - 0.16 * cm
        bar_h = 0.36 * cm
        c.setFillColor(SLATE_200)
        c.roundRect(bar_x, bar_y, bar_w, bar_h, bar_h / 2, fill=1, stroke=0)
        fill_w = max(0.06 * cm, bar_w * (score / 10))
        c.setFillColor(fg)
        c.roundRect(bar_x, bar_y, fill_w, bar_h, bar_h / 2, fill=1, stroke=0)

        c.setFillColor(SLATE_900)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(bar_x, self.height / 2 + 0.42 * cm, f"Risque {label}")
        c.setFillColor(SLATE_500)
        c.setFont("Helvetica", 6)
        for i in range(11):
            c.drawCentredString(bar_x + bar_w * (i / 10), bar_y - 0.3 * cm, str(i))


class SectionHeader(Flowable):
    """Titre de section : barre émeraude + fond clair."""
    def __init__(self, title: str, width: float = 17 * cm):
        Flowable.__init__(self)
        self.title  = title
        self.width  = width
        self.height = 0.82 * cm

    def draw(self):
        c = self.canv
        c.setFillColor(SLATE_100)
        c.roundRect(0, 0, self.width, self.height, 3, fill=1, stroke=0)
        c.setStrokeColor(SLATE_200)
        c.setLineWidth(0.5)
        c.roundRect(0, 0, self.width, self.height, 3, fill=0, stroke=1)
        c.setFillColor(EMERALD_600)
        c.roundRect(0, 0, 0.11 * cm, self.height, 2, fill=1, stroke=0)
        c.setFillColor(SLATE_900)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(0.45 * cm, self.height / 2 - 0.13 * cm, self.title.upper())


# ── Styles ────────────────────────────────────────────────────────────────────
def _build_styles():
    styles = getSampleStyleSheet()

    def add(name, **kw):
        styles.add(ParagraphStyle(name=name, **kw))

    add('BodyText2',   fontName='Helvetica',      fontSize=9,  leading=13, textColor=SLATE_700, spaceAfter=2)
    add('Label',       fontName='Helvetica-Bold',  fontSize=9,  leading=13, textColor=SLATE_900)
    add('Value',       fontName='Helvetica',       fontSize=9,  leading=13, textColor=SLATE_700)
    add('Small',       fontName='Helvetica',       fontSize=7.5,leading=11, textColor=SLATE_500)
    add('SmallBold',   fontName='Helvetica-Bold',  fontSize=7.5,leading=11, textColor=SLATE_700)
    add('FooterText',  fontName='Helvetica',       fontSize=7,  leading=10, textColor=SLATE_500, alignment=TA_CENTER)
    add('MetaRight',   fontName='Helvetica',       fontSize=8,  leading=11, textColor=SLATE_500, alignment=TA_RIGHT)
    add('MetaLabel',   fontName='Helvetica-Bold',  fontSize=8,  leading=11, textColor=SLATE_700)
    add('Transcript',  fontName='Helvetica',       fontSize=8,  leading=12, textColor=SLATE_700)
    add('Disclaimer',  fontName='Helvetica-Oblique', fontSize=8, leading=12, textColor=SLATE_600,
        backColor=SLATE_100, borderPadding=(6, 8, 6, 8))
    add('AnnexTitle',  fontName='Helvetica-Bold',  fontSize=11, leading=16, textColor=SLATE_900)
    return styles


# ── Helpers ───────────────────────────────────────────────────────────────────
def _info_table(rows: List[List], col_widths=(5.5 * cm, 11.5 * cm)) -> Table:
    t = Table(rows, colWidths=list(col_widths))
    t.setStyle(TableStyle([
        ('FONTNAME',       (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME',       (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE',       (0, 0), (-1, -1), 9),
        ('TEXTCOLOR',      (0, 0), (0, -1), SLATE_500),
        ('TEXTCOLOR',      (1, 0), (1, -1), SLATE_900),
        ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',     (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 7),
        ('LEFTPADDING',    (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 10),
        ('LINEBELOW',      (0, 0), (-1, -2), 0.35, SLATE_200),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [WHITE, SLATE_50]),
        ('BOX',            (0, 0), (-1, -1), 0.6, SLATE_200),
    ]))
    return t


def _add_footer(canvas_obj, doc):
    canvas_obj.saveState()
    w, _ = A4
    y    = 1.1 * cm
    canvas_obj.setStrokeColor(EMERALD_600)
    canvas_obj.setLineWidth(1)
    canvas_obj.line(2 * cm, y + 0.55 * cm, w - 2 * cm, y + 0.55 * cm)
    canvas_obj.setFont('Helvetica', 7)
    canvas_obj.setFillColor(SLATE_600)
    canvas_obj.drawString(2 * cm, y + 0.18 * cm, "HelloJADE — Suivi post-hospitalisation automatisé · Epicura")
    canvas_obj.drawRightString(w - 2 * cm, y + 0.18 * cm, f"Page {doc.page}")
    canvas_obj.setFont('Helvetica-Oblique', 6.5)
    canvas_obj.setFillColor(SLATE_400)
    canvas_obj.drawCentredString(w / 2, y - 0.18 * cm, "Document confidentiel — usage médical interne uniquement")
    canvas_obj.restoreState()


def _format_filesize(n: Optional[int]) -> str:
    if not n:
        return "N/A"
    if n < 1024:
        return f"{n} o"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} Ko"
    return f"{n / (1024 * 1024):.2f} Mo"


def _format_duration(seconds) -> str:
    s = int(seconds or 0)
    if s == 0:
        return "N/A"
    if s < 60:
        return f"{s}s"
    return f"{s // 60}min {s % 60:02d}s"


def _format_timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def _parse_date(raw) -> str:
    if not raw:
        return "N/A"
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(str(raw)[:19], fmt[:len(str(raw)[:10])]).strftime("%d/%m/%Y")
        except Exception:
            pass
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(raw)[:10]


def _parse_datetime(raw) -> str:
    if not raw:
        return "N/A"
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y à %H:%M")
    except Exception:
        return str(raw)[:16]


def _group_segments_by_speaker(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not segments:
        return []
    groups: List[Dict[str, Any]] = []
    cur_speaker, cur_texts, cur_start, cur_end = None, [], 0.0, 0.0
    for seg in segments:
        speaker = seg.get("speaker") or ""
        text    = (seg.get("text") or "").strip()
        start   = float(seg.get("start") or 0)
        end     = float(seg.get("end") or 0)
        if not text:
            continue
        if speaker != cur_speaker:
            if cur_texts:
                groups.append({"speaker": cur_speaker, "text": " ".join(cur_texts),
                                "start": cur_start, "end": cur_end})
            cur_speaker, cur_texts, cur_start, cur_end = speaker, [text], start, end
        else:
            cur_texts.append(text)
            cur_end = end
    if cur_texts:
        groups.append({"speaker": cur_speaker, "text": " ".join(cur_texts),
                       "start": cur_start, "end": cur_end})
    return groups


def _resolve_speaker(speaker: str) -> Tuple[str, Any, Any, Any]:
    s = (speaker or "").upper().strip()
    if any(k in s for k in ("JADE", "ROBOT", "BOT", "ASSISTANT", "SPEAKER_0", "SPEAKER_00")):
        return "JADE", EMERALD_100, EMERALD_700, EMERALD_900
    return "Patient", SLATE_100, SLATE_500, SLATE_900


# ── Service ───────────────────────────────────────────────────────────────────
class ReportService:
    def __init__(self):
        self.reports_dir = Path("/app/reports")
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def generate_call_report(
        self,
        call_data:         Dict[str, Any],
        patient_data:      Dict[str, Any],
        transcription_data: Optional[Dict[str, Any]] = None,
        analysis_data:     Optional[Dict[str, Any]] = None,
        call_metadata:     Optional[Dict[str, Any]] = None,
        report_type:       str = "standard",
    ) -> str:
        call_id   = call_data.get("id", "unknown")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename  = f"rapport_{call_id}_{timestamp}.pdf"
        file_path = self.reports_dir / filename

        doc = SimpleDocTemplate(
            str(file_path),
            pagesize=A4,
            rightMargin=2 * cm, leftMargin=2 * cm,
            topMargin=1.4 * cm, bottomMargin=2.5 * cm,
            title="Rapport de Suivi Post-Hospitalisation",
            author="HelloJADE",
            subject=f"Suivi — {patient_data.get('prenom', '')} {patient_data.get('nom', '')}",
        )

        styles  = _build_styles()
        story   = []
        PAGE_W  = A4[0] - 4 * cm   # 17.0 cm
        meta    = call_metadata if isinstance(call_metadata, dict) else {}

        # ══════════════════════════════════════════════════════════════════════
        # PAGE 1 — Rapport clinique
        # ══════════════════════════════════════════════════════════════════════

        # ── 1. Header ─────────────────────────────────────────────────────────
        story.append(HeaderBanner(PAGE_W, LOGO_PATH))
        story.append(Spacer(1, 0.45 * cm))

        # ── 2. Fiche patient ──────────────────────────────────────────────────
        nom_complet = f"{patient_data.get('prenom', '')} {patient_data.get('nom', '')}".strip() or "N/A"
        ddn         = _parse_date(patient_data.get("date_naissance"))
        dossier     = patient_data.get("numero_dossier") or "N/A"
        service     = patient_data.get("service_hospitalisation") or "N/A"
        medecin     = patient_data.get("medecin_referent") or "N/A"
        diagnostic  = patient_data.get("diagnostic_principal") or "—"
        telephone   = patient_data.get("telephone") or "N/A"

        call_dt_str = _parse_datetime(call_data.get("created_at"))
        dur_str     = _format_duration(call_data.get("duration"))
        status_label, status_border, status_bg, status_fg = _get_display_status(call_data)

        # Badge statut
        _slate500 = _hex(SLATE_500)
        status_para = Paragraph(
            f'<font color="{_hex(status_fg)}" size="9"><b>{status_label}</b></font>',
            ParagraphStyle(
                "StatusBadgeText",
                fontName="Helvetica-Bold", fontSize=9,
                alignment=TA_CENTER, textColor=status_fg,
            ),
        )
        status_cell = Table([[status_para]], colWidths=[3.2 * cm])
        status_cell.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), status_bg),
            ("BOX",           (0, 0), (-1, -1), 1.2, status_border),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ]))

        left_col = [
            Paragraph(f"<b>{xml_escape(nom_complet)}</b>", ParagraphStyle(
                "PatientName", fontName="Helvetica-Bold", fontSize=13,
                textColor=SLATE_900, leading=16,
            )),
            Spacer(1, 0.12 * cm),
            Paragraph(
                f'<font color="{_slate500}" size="8">Né(e) le </font>'
                f'<font size="8"><b>{ddn}</b></font>'
                f'<font color="{_slate500}" size="8">  ·  Dossier </font>'
                f'<font size="8"><b>{xml_escape(dossier)}</b></font>',
                styles["BodyText2"],
            ),
            Spacer(1, 0.08 * cm),
            Paragraph(
                f'<font color="{_slate500}" size="8">Diagnostic : </font>'
                f'<font size="8">{xml_escape(diagnostic)}</font>',
                styles["Small"],
            ),
        ]

        right_col = [
            Paragraph(
                f'<font color="{_slate500}" size="8">Unité de soins</font>',
                styles["Small"],
            ),
            Paragraph(f"<b>{xml_escape(service)}</b>", ParagraphStyle(
                "ServiceName", fontName="Helvetica-Bold", fontSize=9.5,
                textColor=SLATE_800, leading=13,
            )),
            Spacer(1, 0.08 * cm),
            Paragraph(
                f'<font color="{_slate500}" size="8">Dr. </font>'
                f'<font size="8"><b>{xml_escape(medecin)}</b></font>',
                styles["Small"],
            ),
            Spacer(1, 0.15 * cm),
            Paragraph(
                f'<font color="{_slate500}" size="7.5">Appel · </font>'
                f'<font size="7.5"><b>{call_dt_str}</b></font>'
                f'<font color="{_slate500}" size="7.5">  ·  Durée </font>'
                f'<font size="7.5"><b>{dur_str}</b></font>',
                styles["Small"],
            ),
            Spacer(1, 0.1 * cm),
            status_cell,
        ]

        patient_card = Table(
            [[left_col, right_col]],
            colWidths=[PAGE_W * 0.56, PAGE_W * 0.44],
        )
        patient_card.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND",    (0, 0), (-1, -1), WHITE),
            ("BOX",           (0, 0), (-1, -1), 0.7, SLATE_200),
            ("TOPPADDING",    (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("LEFTPADDING",   (0, 0), (-1, -1), 12),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
            ("LINEAFTER",     (0, 0), (0, -1), 0.5, SLATE_200),
        ]))
        story.append(patient_card)
        story.append(Spacer(1, 0.5 * cm))

        # ── 3. Résumé encadré déterministe ────────────────────────────────────
        cas, reasons = _determine_case(call_data, analysis_data, call_metadata)
        story.append(SummaryBox(cas, reasons, PAGE_W, call_data))
        story.append(Spacer(1, 0.55 * cm))

        # ── 4. Réponses aux questions ──────────────────────────────────────────
        answers_raw = meta.get("answers") if meta else None
        if isinstance(answers_raw, list) and answers_raw:
            story.append(SectionHeader("Réponses aux questions", PAGE_W))
            story.append(Spacer(1, 0.2 * cm))

            q_header = Table(
                [[
                    Paragraph("<b>Question</b>", styles["SmallBold"]),
                    Paragraph("<b>Réponse du patient</b>", styles["SmallBold"]),
                    Paragraph("<b>Alerte</b>", ParagraphStyle(
                        "AlertHeader", fontName="Helvetica-Bold", fontSize=7.5,
                        alignment=TA_CENTER, textColor=SLATE_700,
                    )),
                ]],
                colWidths=[PAGE_W * 0.38, PAGE_W * 0.47, PAGE_W * 0.15],
            )
            q_header.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), SLATE_900),
                ("TEXTCOLOR",     (0, 0), (-1, -1), WHITE),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ]))
            story.append(q_header)

            q_rows = []
            for i, ans in enumerate(answers_raw):
                if not isinstance(ans, dict):
                    continue
                num        = i + 1
                qtxt       = xml_escape(str(ans.get("question") or "")[:160])
                qid_label  = xml_escape(str(ans.get("question_id") or "")[:40])
                human_ans  = xml_escape(_format_answer_human(ans))
                has_alert  = _answer_has_alert(ans, analysis_data, call_metadata)
                bg         = RED_50 if has_alert else WHITE

                if has_alert:
                    alert_para = Paragraph(
                        '<font color="#B91C1C"><b>⚠ OUI</b></font>',
                        ParagraphStyle("AlertYes", fontName="Helvetica-Bold", fontSize=8,
                                       alignment=TA_CENTER, textColor=RED_MAIN),
                    )
                else:
                    alert_para = Paragraph(
                        '<font color="#047857">✓ Non</font>',
                        ParagraphStyle("AlertNo", fontName="Helvetica", fontSize=8,
                                       alignment=TA_CENTER, textColor=EMERALD_700),
                    )

                row = [
                    Paragraph(
                        f'<font color="{_hex(SLATE_400)}" size="7">Q{num} · {qid_label}</font><br/>'
                        f'<font size="8">{qtxt}</font>',
                        styles["BodyText2"],
                    ),
                    Paragraph(f'<font size="8.5">{human_ans}</font>', styles["BodyText2"]),
                    alert_para,
                ]
                q_rows.append((row, bg, has_alert))

            for row_data, bg, has_alert in q_rows:
                row_t = Table(
                    [row_data],
                    colWidths=[PAGE_W * 0.38, PAGE_W * 0.47, PAGE_W * 0.15],
                )
                border_color = RED_MAIN if has_alert else SLATE_200
                row_t.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, -1), bg),
                    ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING",    (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
                    ("LINEBELOW",     (0, 0), (-1, -1), 0.4, border_color),
                    ("LINEAFTER",     (0, 0), (0, -1), 0.4, SLATE_200),
                    ("LINEAFTER",     (1, 0), (1, -1), 0.4, SLATE_200),
                ]))
                story.append(row_t)

            story.append(Spacer(1, 0.5 * cm))

        # ── 5. Score de risque ────────────────────────────────────────────────
        if analysis_data and analysis_data.get("risk_score") is not None:
            story.append(SectionHeader("Score de risque clinique", PAGE_W))
            story.append(Spacer(1, 0.25 * cm))
            story.append(RiskBadge(int(analysis_data.get("risk_score") or 0), PAGE_W))
            story.append(Spacer(1, 0.5 * cm))

        # ── 6. Alertes cliniques ──────────────────────────────────────────────
        if analysis_data:
            alerts = analysis_data.get("alerts") or []
            if alerts:
                story.append(SectionHeader("Alertes cliniques", PAGE_W))
                story.append(Spacer(1, 0.2 * cm))

                sev_order  = {"urgent": 0, "high": 1, "moderate": 2, "normal": 3}
                sev_labels = {"urgent": "URGENT", "high": "ÉLEVÉ", "moderate": "MODÉRÉ", "normal": "INFO"}
                sev_colors = {
                    "urgent":   (RED_MAIN,    RED_LIGHT),
                    "high":     (ORANGE_MAIN, ORANGE_LIGHT),
                    "moderate": (YELLOW_MAIN, YELLOW_LIGHT),
                    "normal":   (EMERALD_600, EMERALD_50),
                }
                sorted_alerts = sorted(alerts, key=lambda a: sev_order.get(a.get("severity", "normal"), 4))

                for alert in sorted_alerts:
                    sev  = alert.get("severity", "normal")
                    fg, bg = sev_colors.get(sev, (SLATE_600, SLATE_50))
                    label  = sev_labels.get(sev, sev.upper())
                    msg    = xml_escape(str(alert.get("message", "")))

                    row_t = Table(
                        [[
                            Paragraph(f"<b>{label}</b>", ParagraphStyle(
                                f"AlertLbl_{sev}", fontName="Helvetica-Bold", fontSize=8,
                                textColor=fg, alignment=TA_CENTER,
                            )),
                            Paragraph(msg, ParagraphStyle(
                                f"AlertMsg_{sev}", fontName="Helvetica", fontSize=9,
                                textColor=SLATE_900,
                            )),
                        ]],
                        colWidths=[2.8 * cm, PAGE_W - 2.8 * cm],
                    )
                    row_t.setStyle(TableStyle([
                        ("BACKGROUND",    (0, 0), (0, 0), bg),
                        ("BACKGROUND",    (1, 0), (1, 0), WHITE),
                        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING",    (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
                        ("LINEBELOW",     (0, 0), (-1, -1), 0.4, SLATE_200),
                        ("BOX",           (0, 0), (-1, -1), 0.7, fg),
                    ]))
                    story.append(row_t)
                    story.append(Spacer(1, 0.1 * cm))

                story.append(Spacer(1, 0.4 * cm))

        # ── 7. Recommandations ────────────────────────────────────────────────
        if analysis_data and analysis_data.get("recommendations"):
            recs = [r for r in analysis_data["recommendations"] if r]
            if recs:
                story.append(SectionHeader("Recommandations", PAGE_W))
                story.append(Spacer(1, 0.2 * cm))
                rec_rows = [[Paragraph(f"• {xml_escape(str(r))}", styles["BodyText2"])] for r in recs]
                rec_t = Table(rec_rows, colWidths=[PAGE_W])
                rec_t.setStyle(TableStyle([
                    ("TOPPADDING",     (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
                    ("LEFTPADDING",    (0, 0), (-1, -1), 10),
                    ("LINEBELOW",      (0, 0), (-1, -2), 0.4, SLATE_200),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, SLATE_50]),
                    ("BOX",            (0, 0), (-1, -1), 0.6, SLATE_200),
                ]))
                story.append(rec_t)
                story.append(Spacer(1, 0.5 * cm))

        # ── 8. Disclaimer IA ──────────────────────────────────────────────────
        disclaimer_t = Table(
            [[Paragraph(
                "⚠  Ce rapport est généré par un système basé sur l'intelligence artificielle pour "
                "la retranscription et le résumé des réponses. Il peut commettre des erreurs. "
                "Il ne remplace pas le jugement clinique du professionnel de santé.",
                styles["Disclaimer"],
            )]],
            colWidths=[PAGE_W],
        )
        disclaimer_t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), SLATE_100),
            ("BOX",           (0, 0), (-1, -1), 0.8, SLATE_400),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(KeepTogether(disclaimer_t))

        # ══════════════════════════════════════════════════════════════════════
        # PAGE 2 — Annexe : Transcription de l'appel
        # ══════════════════════════════════════════════════════════════════════
        has_segments  = bool(transcription_data and transcription_data.get("segments"))
        has_full_text = bool(transcription_data and transcription_data.get("full_text"))

        if has_segments or has_full_text:
            story.append(PageBreak())

            # Titre annexe
            story.append(Paragraph("ANNEXE — Transcription de l'appel", styles["AnnexTitle"]))
            story.append(Spacer(1, 0.1 * cm))
            story.append(Paragraph(
                f"{nom_complet}  ·  {call_dt_str}  ·  Durée : {dur_str}",
                styles["Small"],
            ))
            story.append(Spacer(1, 0.15 * cm))
            story.append(HRFlowable(width=PAGE_W, thickness=1, color=EMERALD_600))
            story.append(Spacer(1, 0.3 * cm))

            # Métadonnées transcription
            if transcription_data:
                meta_parts = []
                lang  = transcription_data.get("language")
                conf  = transcription_data.get("confidence")
                asize = transcription_data.get("audio_size_bytes")
                if lang:
                    meta_parts.append(f"Langue : {lang}")
                if conf is not None:
                    meta_parts.append(f"Confiance ASR : {round(conf * 100)}%")
                if asize:
                    meta_parts.append(f"Audio : {_format_filesize(asize)}")
                if meta_parts:
                    story.append(Paragraph("  ·  ".join(meta_parts), styles["Small"]))
                    story.append(Spacer(1, 0.25 * cm))

            # Dialogue
            if has_segments:
                groups = _group_segments_by_speaker(transcription_data["segments"])
                for turn in groups:
                    label, bg_color, accent_color, text_color = _resolve_speaker(turn["speaker"])
                    ts = _format_timestamp(turn["start"])

                    row_t = Table(
                        [[
                            Paragraph(
                                f"<b>{label}</b><br/>"
                                f'<font size="6.5">{ts}</font>',
                                ParagraphStyle(
                                    "TurnLabel", fontName="Helvetica-Bold", fontSize=8,
                                    leading=11, textColor=accent_color,
                                ),
                            ),
                            Paragraph(
                                xml_escape(turn["text"]),
                                ParagraphStyle(
                                    "TurnText", fontName="Helvetica", fontSize=8,
                                    leading=12, textColor=text_color,
                                ),
                            ),
                        ]],
                        colWidths=[2.1 * cm, PAGE_W - 2.1 * cm],
                    )
                    row_t.setStyle(TableStyle([
                        ("BACKGROUND",    (0, 0), (-1, -1), bg_color),
                        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
                        ("TOPPADDING",    (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("LINEBELOW",     (0, 0), (-1, -1), 0.3, SLATE_200),
                    ]))
                    story.append(KeepTogether(row_t))

            elif has_full_text:
                fb_t = Table(
                    [[Paragraph(xml_escape(transcription_data["full_text"]), styles["Transcript"])]],
                    colWidths=[PAGE_W],
                )
                fb_t.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, -1), SLATE_50),
                    ("BOX",           (0, 0), (-1, -1), 0.5, SLATE_200),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
                    ("TOPPADDING",    (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]))
                story.append(fb_t)

        # ── Build ─────────────────────────────────────────────────────────────
        doc.build(story, onFirstPage=_add_footer, onLaterPages=_add_footer)
        logger.info(f"✅ Rapport PDF généré : {file_path}")
        return str(file_path)


report_service = ReportService()
