# Zulip Clubhouse integration

Get Zulip notifications for your Clubhouse Stories and Epics!

{start_tabs}

1. {!create-channel.md!}

1. {!create-an-incoming-webhook.md!}

1. {!generate-webhook-url-basic.md!}

1. Go to your Clubhouse Dashboard, and click on the settings icon in the
   top-right corner. Go to **Integrations**, and select **Webhooks**.
   Click **+ Add New Webhook**.

1. Set **Payload URL** to the URL generated above, and click **Add New
   Webhook**.

{end_tabs}

{!congrats.md!}

![](/static/images/integrations/clubhouse/001.png)

{% if all_event_types is defined %}

{!event-filtering-additional-feature.md!}

{% endif %}

### Related documentation

{!webhooks-url-specification.md!}
