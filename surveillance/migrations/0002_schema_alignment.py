"""
Align the schema with the design document:

- Monitor.expected_status_codes becomes a list ([200, 201, ...]) instead of one int.
- ApiLog.created_at -> checked_at, plus the (monitor, checked_at, region) unique
  constraint that makes duplicate check writes impossible at the DB layer.
- Incident gains a partial unique index: at most one unresolved incident per monitor.
- ApiToken gains organization / prefix / last_used_at / expires_at / created_at.
- StatusPage.slug is a unique slug; Subscriber is unique per (page, email).

All affected tables were empty when this was written, so no data migration is needed.
"""

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

import surveillance.models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0007_alter_organization_id_alter_organizationmember_id_and_more'),
        ('surveillance', '0001_initial'),
    ]

    operations = [
        # --- Monitor -------------------------------------------------------
        # Postgres cannot cast integer -> jsonb in place, and the table is empty,
        # so drop and re-add rather than write a USING clause for no data.
        migrations.RemoveField(
            model_name='monitor',
            name='expected_status_codes',
        ),
        migrations.AddField(
            model_name='monitor',
            name='expected_status_codes',
            field=models.JSONField(
                default=surveillance.models.default_status_codes,
                help_text='List of status codes treated as healthy, e.g. [200, 201, 204].',
            ),
        ),

        # --- ApiLog --------------------------------------------------------
        migrations.RemoveIndex(
            model_name='apilog',
            name='surveillanc_monitor_86c45e_idx',
        ),
        migrations.RenameField(
            model_name='apilog',
            old_name='created_at',
            new_name='checked_at',
        ),
        migrations.AlterField(
            model_name='apilog',
            name='checked_at',
            field=models.DateTimeField(db_index=True, default=django.utils.timezone.now),
        ),
        migrations.AddIndex(
            model_name='apilog',
            index=models.Index(fields=['monitor', '-checked_at'], name='apilog_monitor_checked_idx'),
        ),
        migrations.AddConstraint(
            model_name='apilog',
            constraint=models.UniqueConstraint(
                fields=('monitor', 'checked_at', 'region'),
                name='unique_check_per_monitor_time_region',
            ),
        ),

        # --- Incident ------------------------------------------------------
        migrations.AddConstraint(
            model_name='incident',
            constraint=models.UniqueConstraint(
                condition=models.Q(('resolved_at__isnull', True)),
                fields=('monitor',),
                name='unique_open_incident_per_monitor',
            ),
        ),

        # --- ApiToken ------------------------------------------------------
        migrations.AddField(
            model_name='apitoken',
            name='organization',
            field=models.ForeignKey(
                default=None,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='api_tokens',
                to='organizations.organization',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='apitoken',
            name='prefix',
            field=models.CharField(default='', max_length=16),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='apitoken',
            name='last_used_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='apitoken',
            name='expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='apitoken',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='apitoken',
            name='token_hash',
            field=models.CharField(db_index=True, max_length=64, unique=True),
        ),
        # Tokens are org-scoped; the column is only nullable above so the ADD
        # COLUMN succeeds on an existing table. Nothing to backfill (0 rows).
        migrations.AlterField(
            model_name='apitoken',
            name='organization',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='api_tokens',
                to='organizations.organization',
            ),
        ),

        # --- StatusPage / StatusPageMonitor / Subscriber --------------------
        migrations.AlterField(
            model_name='statuspage',
            name='slug',
            field=models.SlugField(max_length=63, unique=True),
        ),
        migrations.AlterModelOptions(
            name='statuspagemonitor',
            options={'ordering': ['display_order', 'id']},
        ),
        migrations.AlterUniqueTogether(
            name='statuspagemonitor',
            unique_together={('status_page', 'monitor')},
        ),
        migrations.AlterField(
            model_name='subscriber',
            name='verification_token',
            field=models.CharField(db_index=True, max_length=64),
        ),
        migrations.AlterUniqueTogether(
            name='subscriber',
            unique_together={('status_page', 'email')},
        ),
    ]
