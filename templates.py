# templates.py — copy EXACTLY, do not edit wording

TEMPLATE_ANSWER = (
    "Here's what the approved KESIMPTA information says:\n\n"
    "{answer}\n\n"
    "For questions about your own situation, please talk to your healthcare provider."
)

TEMPLATE_RELATED = (
    "I couldn't find an exact answer to that, but this approved information may help:\n\n"
    "{answer}"
)

TEMPLATE_ADVICE = (
    "That's an important question, and the right answer depends on your personal health, "
    "so I can't advise on it. Please talk to your healthcare provider, who knows your "
    "history and can help you decide."
)

TEMPLATE_RED_URGENT = (
    "This could be a medical emergency. If you have trouble breathing, swelling of your face, "
    "lips, tongue or throat, chest tightness, or feel faint, call your local emergency number now.\n\n"
    "When you can, please also tell your healthcare provider. You can report side effects to "
    "Novartis at 1-888-669-6682 or to the FDA at 1-800-FDA-1088."
)

TEMPLATE_RED_SIDE_EFFECT = (
    "Thank you for telling us. What you describe could be a side effect, and it's important that a "
    "healthcare professional knows about it.\n\n"
    "If you have trouble breathing, swelling of your face, lips, tongue or throat, or chest tightness, "
    "call your local emergency number now.\n\n"
    "Otherwise, please contact your healthcare provider as soon as possible. You can also report side "
    "effects to Novartis at 1-888-669-6682 or to the FDA at 1-800-FDA-1088.\n\n"
    "I'm not able to give medical advice, so I can't continue with this topic here."
)

TEMPLATE_RED_PREGNANCY = (
    "Thank you for letting us know. If you become pregnant while using KESIMPTA, it's important to "
    "tell your healthcare provider right away.\n\n"
    "There is a pregnancy registry for women who become pregnant during treatment with KESIMPTA. "
    "You can contact MotherToBaby at 1-877-311-8972 or www.mothertobaby.org/join-study, "
    "and Novartis at 1-888-669-6682."
)

TEMPLATE_RED_COMPLAINT = (
    "Thank you for letting us know. Please don't use a pen that seems damaged or isn't working as "
    "expected. Keep it, and contact Novartis at 1-888-669-6682 so the issue can be looked into. "
    "If you've had any symptoms, please also contact your healthcare provider."
)

TEMPLATE_NO_ANSWER = (
    "I don't have an approved answer for that yet. Your healthcare provider or pharmacist can help, "
    "or you can call Novartis at 1-888-669-6682. For help getting started on treatment, "
    "Novartis Patient Support is at 855-537-4678."
)

TEMPLATE_OFF_TOPIC = (
    "I can only help with questions about KESIMPTA, using its approved patient information. "
    "You could ask about using the pen, storing it, or possible side effects."
)

TEMPLATE_ERROR = (
    "Sorry, I can't answer right now. Please try again in a moment. "
    "If you're having side effects or need medical help, contact your healthcare provider."
)

BANNER = (
    "Prototype for a hackathon demo — not for patient use. Uses public KESIMPTA information only. "
    "Reports entered here are not sent to Novartis."
)

# Starter questions point at brochure content (pen, support, side effects, storage).
STARTERS = [
    "How does the auto-injector pen work?",
    "What support is available to me?",
    "What are the most common side effects?",
    "How should I store my pen?",
]
