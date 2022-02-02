# Generated by Django 3.1.13 on 2022-02-02 22:01

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_auto_20220128_2000'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='incident',
            options={'ordering': ['-start_year', '-start_month', '-start_day', '-end_year', '-end_month', '-end_day', 'location'], 'verbose_name': 'Incident'},
        ),
        migrations.AlterModelOptions(
            name='persongrouping',
            options={'ordering': ['-start_year', '-start_month', '-start_day', '-end_year', '-end_month', '-end_day', 'grouping', 'person'], 'verbose_name': 'Link between person and grouping', 'verbose_name_plural': 'Links between people and groupings'},
        ),
        migrations.AlterModelOptions(
            name='personidentifier',
            options={'ordering': ['person', 'person_identifier_type', '-start_year', '-start_month', '-start_day', '-end_year', '-end_month', '-end_day'], 'verbose_name': 'Person identifier'},
        ),
        migrations.AlterModelOptions(
            name='personpayment',
            options={'ordering': ['person', '-start_year', '-start_month', '-start_day', '-end_year', '-end_month', '-end_day'], 'verbose_name': 'person payment'},
        ),
        migrations.AlterModelOptions(
            name='persontitle',
            options={'ordering': ['person', '-start_year', '-start_month', '-start_day', '-end_year', '-end_month', '-end_day'], 'verbose_name': 'Person title'},
        ),
        migrations.AlterField(
            model_name='groupingrelationship',
            name='at_least_since',
            field=models.BooleanField(default=False, help_text='Select if start date is the earliest known start date, but not necessarily the true start date'),
        ),
        migrations.AlterField(
            model_name='persongrouping',
            name='at_least_since',
            field=models.BooleanField(default=False, help_text='Select if start date is the earliest known start date, but not necessarily the true start date'),
        ),
        migrations.AlterField(
            model_name='personidentifier',
            name='at_least_since',
            field=models.BooleanField(default=False, help_text='Select if start date is the earliest known start date, but not necessarily the true start date'),
        ),
        migrations.AlterField(
            model_name='personpayment',
            name='at_least_since',
            field=models.BooleanField(default=False, help_text='Select if start date is the earliest known start date, but not necessarily the true start date'),
        ),
        migrations.AlterField(
            model_name='personrelationship',
            name='at_least_since',
            field=models.BooleanField(default=False, help_text='Select if start date is the earliest known start date, but not necessarily the true start date'),
        ),
        migrations.AlterField(
            model_name='persontitle',
            name='at_least_since',
            field=models.BooleanField(default=False, help_text='Select if start date is the earliest known start date, but not necessarily the true start date'),
        ),
    ]
