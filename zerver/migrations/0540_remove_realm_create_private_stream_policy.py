# Generated by Django 5.0.6 on 2024-06-17 14:43

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("zerver", "0539_alter_realm_can_create_private_channel_group"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="realm",
            name="create_private_stream_policy",
        ),
    ]