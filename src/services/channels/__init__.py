"""Channel adapters for different communication platforms."""

from src.services.channels.base import ChannelAdapter
from src.services.channels.whatsapp import TwilioWhatsAppAdapter

__all__ = ["ChannelAdapter", "TwilioWhatsAppAdapter"]
