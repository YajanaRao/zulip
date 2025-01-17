from typing import Dict, List

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils.translation import gettext as _
from django.utils.translation import override as override_language

from zerver.actions.create_realm import setup_realm_internal_bots
from zerver.actions.message_send import (
    do_send_messages,
    internal_prep_stream_message_by_name,
    internal_send_private_message,
)
from zerver.actions.reactions import do_add_reaction
from zerver.lib.emoji import get_emoji_data
from zerver.lib.message import SendMessageRequest, remove_single_newlines
from zerver.models import Message, OnboardingUserMessage, Realm, UserProfile
from zerver.models.users import get_system_bot


def missing_any_realm_internal_bots() -> bool:
    bot_emails = [
        bot["email_template"] % (settings.INTERNAL_BOT_DOMAIN,)
        for bot in settings.REALM_INTERNAL_BOTS
    ]
    realm_count = Realm.objects.count()
    return UserProfile.objects.filter(email__in=bot_emails).values("email").annotate(
        count=Count("id")
    ).filter(count=realm_count).count() != len(bot_emails)


def create_if_missing_realm_internal_bots() -> None:
    """This checks if there is any realm internal bot missing.

    If that is the case, it creates the missing realm internal bots.
    """
    if missing_any_realm_internal_bots():
        for realm in Realm.objects.all():
            setup_realm_internal_bots(realm)


def send_initial_direct_message(user: UserProfile) -> int:
    # We adjust the initial Welcome Bot direct message for education organizations.
    education_organization = user.realm.org_type in (
        Realm.ORG_TYPES["education_nonprofit"]["id"],
        Realm.ORG_TYPES["education"]["id"],
    )

    # We need to override the language in this code path, because it's
    # called from account registration, which is a pre-account API
    # request and thus may not have the user's language context yet.
    with override_language(user.default_language):
        if education_organization:
            getting_started_string = _("""
If you are new to Zulip, check out our [Using Zulip for a class guide]({getting_started_url})!
""").format(getting_started_url="/help/using-zulip-for-a-class")
        else:
            getting_started_string = _("""
If you are new to Zulip, check out our [Getting started guide]({getting_started_url})!
""").format(getting_started_url="/help/getting-started-with-zulip")

        organization_setup_string = ""
        # Add extra content on setting up a new organization for administrators.
        if user.is_realm_admin:
            if education_organization:
                organization_setup_string = _("""
We also have a guide for [Setting up Zulip for a class]({organization_setup_url}).
""").format(organization_setup_url="/help/setting-up-zulip-for-a-class")
            else:
                organization_setup_string = _("""
We also have a guide for [Setting up your organization]({organization_setup_url}).
""").format(organization_setup_url="/help/getting-your-organization-started-with-zulip")

        demo_organization_warning_string = ""
        # Add extra content about automatic deletion for demo organization owners.
        if user.is_realm_owner and user.realm.demo_organization_scheduled_deletion_date is not None:
            demo_organization_warning_string = _("""
Note that this is a [demo organization]({demo_organization_help_url}) and
will be **automatically deleted** in 30 days.
""").format(demo_organization_help_url="/help/demo-organizations")

        content = _("""
Hello, and welcome to Zulip!👋 This is a direct message from me, Welcome Bot.

{getting_started_text} {organization_setup_text}

{demo_organization_text}

I can also help you get set up! Just click anywhere on this message or press `r` to reply.

Here are a few messages I understand: {bot_commands}
""").format(
            getting_started_text=getting_started_string,
            organization_setup_text=organization_setup_string,
            demo_organization_text=demo_organization_warning_string,
            bot_commands=bot_commands(),
        )

    message_id = internal_send_private_message(
        get_system_bot(settings.WELCOME_BOT, user.realm_id),
        user,
        remove_single_newlines(content),
        # Note: Welcome bot doesn't trigger email/push notifications,
        # as this is intended to be seen contextually in the application.
        disable_external_notifications=True,
    )
    assert message_id is not None
    return message_id


def bot_commands(no_help_command: bool = False) -> str:
    commands = [
        "apps",
        "profile",
        "theme",
        "channels",
        "topics",
        "message formatting",
        "keyboard shortcuts",
    ]
    if not no_help_command:
        commands.append("help")
    return ", ".join("`" + command + "`" for command in commands) + "."


def select_welcome_bot_response(human_response_lower: str) -> str:
    # Given the raw (pre-markdown-rendering) content for a private
    # message from the user to Welcome Bot, select the appropriate reply.
    if human_response_lower in ["app", "apps"]:
        return _("""
You can [download](/apps/) the [mobile and desktop apps](/apps/).
Zulip also works great in a browser.
""")
    elif human_response_lower == "profile":
        return _("""
Go to [Profile settings](#settings/profile) to add a [profile picture](/help/change-your-profile-picture)
and edit your [profile information](/help/edit-your-profile).
""")
    elif human_response_lower == "theme":
        return _("""
Go to [Preferences](#settings/preferences) to [switch between the light and dark themes](/help/dark-theme),
[pick your favorite emoji theme](/help/emoji-and-emoticons#change-your-emoji-set),
[change your language](/help/change-your-language), and make other tweaks
to your Zulip experience.
""")
    elif human_response_lower in ["stream", "streams", "channel", "channels"]:
        return _("""
In Zulip, channels [determine who gets a message]({help_link}).

[Browse and subscribe to channels]({settings_link}).
""").format(help_link="/help/introduction-to-channels", settings_link="#channels/all")
    elif human_response_lower in ["topic", "topics"]:
        return _("""
In Zulip, topics [tell you what a message is about](/help/introduction-to-topics).
They are light-weight subjects, very similar to the subject line of an email.

Check out [Recent conversations](#recent) to see what's happening!
You can return to this conversation by clicking "Direct messages" in the upper left.
""")
    elif human_response_lower in ["keyboard", "shortcuts", "keyboard shortcuts"]:
        return _("""
Zulip's [keyboard shortcuts](#keyboard-shortcuts) let you navigate the app
quickly and efficiently.

Press `?` any time to see a [cheat sheet](#keyboard-shortcuts).
""")
    elif human_response_lower in ["formatting", "message formatting"]:
        return _("""
Zulip uses [Markdown](/help/format-your-message-using-markdown),
an intuitive format for **bold**, *italics*, bulleted lists, and more.
Click [here](#message-formatting) for a cheat sheet.

Check out our [messaging tips](/help/messaging-tips) to learn
about emoji reactions, code blocks and much more!
""")
    elif human_response_lower in ["help", "?"]:
        return _("""
Here are a few messages I understand: {bot_commands}

Check out our [Getting started guide](/help/getting-started-with-zulip),
or browse the [Help center](/help/) to learn more!
""").format(bot_commands=bot_commands(no_help_command=True))
    else:
        return _("""
I’m sorry, I did not understand your message. Please try
one of the following commands: {bot_commands}
""").format(bot_commands=bot_commands())


def send_welcome_bot_response(send_request: SendMessageRequest) -> None:
    """Given the send_request object for a direct message from the user
    to welcome-bot, trigger the welcome-bot reply."""
    welcome_bot = get_system_bot(settings.WELCOME_BOT, send_request.realm.id)
    human_response_lower = send_request.message.content.lower()
    content = select_welcome_bot_response(human_response_lower)

    internal_send_private_message(
        welcome_bot,
        send_request.message.sender,
        remove_single_newlines(content),
        # Note: Welcome bot doesn't trigger email/push notifications,
        # as this is intended to be seen contextually in the application.
        disable_external_notifications=True,
    )


@transaction.atomic
def send_initial_realm_messages(realm: Realm) -> None:
    # Sends the initial messages for a new organization.
    #
    # Technical note: Each stream created in the realm creation
    # process should have at least one message declared in this
    # function, to enforce the pseudo-invariant that every stream has
    # at least one message.
    welcome_bot = get_system_bot(settings.WELCOME_BOT, realm.id)

    # Content is declared here to apply translation properly.
    #
    # remove_single_newlines needs to be called on any multiline
    # strings for them to render properly.
    content1_of_moving_messages_topic_name = (
        _("""
If anything is out of place, it’s easy to [move messages]({move_content_another_topic_help_url}),
[rename]({rename_topic_help_url}) and [split]({move_content_another_topic_help_url}) topics,
or even move a topic [to a different channel]({move_content_another_channel_help_url}).
""")
    ).format(
        move_content_another_topic_help_url="/help/move-content-to-another-topic",
        rename_topic_help_url="/help/rename-a-topic",
        move_content_another_channel_help_url="/help/move-content-to-another-channel",
    )

    content2_of_moving_messages_topic_name = _("""
:point_right: Try moving this message to another topic and back.
""")

    content1_of_welcome_to_zulip_topic_name = _("""
Zulip is organized to help you communicate more efficiently. Conversations are
labeled with topics, which summarize what the conversation is about.

For example, this message is in the “{topic_name}” topic in the
#**{zulip_discussion_channel_name}** channel, as you can see in the left sidebar
and above.
""").format(
        zulip_discussion_channel_name=str(Realm.ZULIP_DISCUSSION_CHANNEL_NAME),
        topic_name=_("welcome to Zulip!"),
    )

    content2_of_welcome_to_zulip_topic_name = _("""
You can read Zulip one conversation at a time, seeing each message in context,
no matter how many other conversations are going on.
""")

    content3_of_welcome_to_zulip_topic_name = _("""
:point_right: When you're ready, check out your [Inbox](/#inbox) for other
conversations with unread messages.
""")

    content1_of_start_conversation_topic_name = _("""
To kick off a new conversation, click **Start new conversation** below.
The new conversation thread will be labeled with its own topic.
""")

    content2_of_start_conversation_topic_name = _("""
For a good topic name, think about finishing the sentence: “Hey, can we chat about…?”
""")

    content3_of_start_conversation_topic_name = _("""
:point_right: Try starting a new conversation in this channel.
""")

    content1_of_experiments_topic_name = (
        _("""
:point_right:  Use this topic to try out [Zulip's messaging features]({format_message_help_url}).
""")
    ).format(format_message_help_url="/help/format-your-message-using-markdown")

    content2_of_experiments_topic_name = (
        _("""
```spoiler Want to see some examples?

````python
print("code blocks")
````

- bulleted
- lists

Link to a conversation: #**{zulip_discussion_channel_name}>{topic_name}**
```
""")
    ).format(
        zulip_discussion_channel_name=str(Realm.ZULIP_DISCUSSION_CHANNEL_NAME),
        topic_name=_("welcome to Zulip!"),
    )

    content1_of_greetings_topic_name = _("""
This **greetings** topic is a great place to say “hi” :wave: to your teammates.
""")

    content2_of_greetings_topic_name = _("""
:point_right: Click on this message to start a new message in the same conversation.
""")

    welcome_messages: List[Dict[str, str]] = []

    # Messages added to the "welcome messages" list last will be most
    # visible to users, since welcome messages will likely be browsed
    # via the right sidebar or recent conversations view, both of
    # which are sorted newest-first.
    #
    # Initial messages are configured below.

    # Advertising moving messages.
    welcome_messages += [
        {
            "channel_name": str(Realm.ZULIP_DISCUSSION_CHANNEL_NAME),
            "topic_name": _("moving messages"),
            "content": content,
        }
        for content in [
            content1_of_moving_messages_topic_name,
            content2_of_moving_messages_topic_name,
        ]
    ]

    # Suggestion to test messaging features.
    # Dependency on knowing how to send messages.
    welcome_messages += [
        {
            "channel_name": str(realm.ZULIP_SANDBOX_CHANNEL_NAME),
            "topic_name": _("experiments"),
            "content": content,
        }
        for content in [content1_of_experiments_topic_name, content2_of_experiments_topic_name]
    ]

    # Suggestion to start your first new conversation.
    welcome_messages += [
        {
            "channel_name": str(realm.ZULIP_SANDBOX_CHANNEL_NAME),
            "topic_name": _("start a conversation"),
            "content": content,
        }
        for content in [
            content1_of_start_conversation_topic_name,
            content2_of_start_conversation_topic_name,
            content3_of_start_conversation_topic_name,
        ]
    ]

    # Suggestion to send first message as a hi to your team.
    welcome_messages += [
        {
            "channel_name": str(Realm.DEFAULT_NOTIFICATION_STREAM_NAME),
            "topic_name": _("greetings"),
            "content": content,
        }
        for content in [content1_of_greetings_topic_name, content2_of_greetings_topic_name]
    ]

    # Main welcome message, this should be last.
    welcome_messages += [
        {
            "channel_name": str(realm.ZULIP_DISCUSSION_CHANNEL_NAME),
            "topic_name": _("welcome to Zulip!"),
            "content": content,
        }
        for content in [
            content1_of_welcome_to_zulip_topic_name,
            content2_of_welcome_to_zulip_topic_name,
            content3_of_welcome_to_zulip_topic_name,
        ]
    ]

    # End of message declarations; now we actually send them.

    messages = [
        internal_prep_stream_message_by_name(
            realm,
            welcome_bot,
            message["channel_name"],
            message["topic_name"],
            remove_single_newlines(message["content"]),
        )
        for message in welcome_messages
    ]
    message_ids = [
        sent_message_result.message_id for sent_message_result in do_send_messages(messages)
    ]

    seen_topics = set()
    onboarding_topics_first_message_ids = set()
    for index, message in enumerate(welcome_messages):
        topic_name = message["topic_name"]
        if topic_name not in seen_topics:
            onboarding_topics_first_message_ids.add(message_ids[index])
            seen_topics.add(topic_name)

    onboarding_user_messages = []
    for message_id in message_ids:
        flags = OnboardingUserMessage.flags.historical
        if message_id in onboarding_topics_first_message_ids:
            flags |= OnboardingUserMessage.flags.starred
        onboarding_user_messages.append(
            OnboardingUserMessage(realm=realm, message_id=message_id, flags=flags)
        )

    OnboardingUserMessage.objects.bulk_create(onboarding_user_messages)

    # We find the one of our just-sent greetings messages, and react to it.
    # This is a bit hacky, but works and is kinda a 1-off thing.
    greetings_message = (
        Message.objects.select_for_update()
        .filter(
            id__in=message_ids, content=remove_single_newlines(content1_of_greetings_topic_name)
        )
        .first()
    )
    assert greetings_message is not None
    emoji_data = get_emoji_data(realm.id, "wave")
    do_add_reaction(
        welcome_bot, greetings_message, "wave", emoji_data.emoji_code, emoji_data.reaction_type
    )
