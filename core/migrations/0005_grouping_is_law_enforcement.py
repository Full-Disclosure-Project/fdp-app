# Generated by Django 3.1.13 on 2021-11-08 20:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_auto_20210813_1432'),
    ]

    operations = [
        migrations.AddField(
            model_name='grouping',
            name='is_law_enforcement',
            field=models.BooleanField(default=False, help_text='Select if grouping is part of law enforcement', verbose_name='Is law enforcement'),
        ),
    ]
