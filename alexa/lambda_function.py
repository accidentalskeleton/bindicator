"""AWS Lambda entry point for private Bindicator Alexa skill.

Requires ask-sdk-core and a Lambda Alexa Skills Kit trigger restricted to the
correct skill ID. Also enforces ALEXA_SKILL_ID at SDK level. It is not an
HTTP webhook and must not be exposed through cloudflared directly.
"""
from __future__ import annotations

import logging
import os

from ask_sdk_core.dispatch_components import (
    AbstractExceptionHandler, AbstractRequestHandler,
)
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import get_supported_interfaces, is_intent_name, is_request_type
from ask_sdk_model.ui import SimpleCard
from ask_sdk_model.interfaces.alexa.presentation.apl import RenderDocumentDirective

from alexa.logic import (AlexaConfigError, BindicatorUnavailable, call_api,
                         card_content, handle_intent, speech_xml)
from alexa.apl import DOCUMENT_TOKEN, document, presentation, valid_bins_out_event

LOG = logging.getLogger("bindicator.alexa")
INTENTS = (
    "PauseIntent", "ResumeIntent", "ToggleIntent", "StatusIntent",
    "NextCollectionIntent", "ShowNextIntent", "ShowPersistentIntent",
    "BinsOutIntent",
)



def attach_echo_show(handler_input):
    """Add APL only to supported devices; speech remains functional on errors."""
    supported = get_supported_interfaces(handler_input)
    if supported is None or supported.alexa_presentation_apl is None:
        return
    try:
        next_collection = call_api("GET", "/api/v1/collections/next")
        status = call_api("GET", "/api/v1/status")
        handler_input.response_builder.add_directive(
            RenderDocumentDirective(
                token=DOCUMENT_TOKEN,
                document=document(),
                datasources=presentation(next_collection, status),
            )
        )
    except (AlexaConfigError, BindicatorUnavailable, ValueError, OSError):
        # Alexa speech and cards should work when APL data is unavailable.
        LOG.warning("Echo Show visual data unavailable")


class LaunchHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        welcome = (
            "Bin Indicator is ready. You can ask what bins are next, "
            "pause reminders, or show the bins for ten seconds."
        )
        response_builder = handler_input.response_builder.speak(welcome).ask(
            "What would you like to do?"
        ).set_card(SimpleCard("Bindicator", welcome))
        attach_echo_show(handler_input)
        return response_builder.response


class KnownIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return any(is_intent_name(name)(handler_input) for name in INTENTS)

    def handle(self, handler_input):
        intent = handler_input.request_envelope.request.intent
        slots = {}
        for name, slot in (intent.slots or {}).items():
            slots[name] = {"value": slot.value}
        response = handle_intent(intent.name, slots=slots)
        # The Alexa SDK serialises speech into valid SSML. Escape untrusted
        # text such as event titles to prevent unintended SSML markup.
        card_title, card_text = card_content(intent.name, response)
        builder = handler_input.response_builder.speak(
            speech_xml(response)
        ).set_card(SimpleCard(card_title, card_text)).set_should_end_session(True)
        if "couldn\'t reach Bin Indicator" not in response:
            attach_echo_show(handler_input)
        return builder.response



class BinsOutTouchHandler(AbstractRequestHandler):
    """The sole accepted APL touch action; never trust arbitrary event arguments."""

    def can_handle(self, handler_input):
        return is_request_type("Alexa.Presentation.APL.UserEvent")(handler_input)

    def handle(self, handler_input):
        request = handler_input.request_envelope.request
        if not valid_bins_out_event(request):
            return handler_input.response_builder.speak(
                "That Bin Buddy control is not available."
            ).set_should_end_session(True).response
        response = handle_intent("BinsOutIntent")
        builder = handler_input.response_builder.speak(
            speech_xml(response)
        ).set_card(SimpleCard("Bins put out", response)).set_should_end_session(True)
        if "couldn't reach Bin Indicator" not in response:
            attach_echo_show(handler_input)
        return builder.response


class HelpHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input) or is_intent_name(
            "AMAZON.FallbackIntent"
        )(handler_input)

    def handle(self, handler_input):
        help_text = (
            "You can say what bins are next, pause reminders, resume reminders, "
            "show the next bins for ten seconds, or say the bins are out."
        )
        return handler_input.response_builder.speak(help_text).ask(
            "What would you like to do?"
        ).set_card(SimpleCard("Bindicator help", help_text)).response


class StopHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return (
            is_intent_name("AMAZON.StopIntent")(handler_input)
            or is_intent_name("AMAZON.CancelIntent")(handler_input)
            or is_request_type("SessionEndedRequest")(handler_input)
        )

    def handle(self, handler_input):
        return handler_input.response_builder.speak(
            "Goodbye."
        ).set_should_end_session(True).response


class ErrorHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        LOG.exception("Alexa handler error: %s", type(exception).__name__)
        return handler_input.response_builder.speak(
            "Bin Indicator couldn't complete that request. Please try again."
        ).set_should_end_session(True).response


def create_lambda_handler():
    skill_id = os.environ.get("ALEXA_SKILL_ID", "")
    if not skill_id.startswith("amzn1.ask.skill."):
        raise RuntimeError(
            "Set ALEXA_SKILL_ID to your skill ID before deploying the Lambda."
        )
    builder = SkillBuilder()
    builder.skill_id = skill_id
    builder.add_request_handler(LaunchHandler())
    builder.add_request_handler(KnownIntentHandler())
    builder.add_request_handler(BinsOutTouchHandler())
    builder.add_request_handler(HelpHandler())
    builder.add_request_handler(StopHandler())
    builder.add_exception_handler(ErrorHandler())
    return builder.lambda_handler()


lambda_handler = create_lambda_handler()
