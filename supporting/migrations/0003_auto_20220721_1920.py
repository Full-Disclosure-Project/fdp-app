# Generated by Django 3.1.14 on 2022-07-21 19:20

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('supporting', '0002_auto_20210811_1832'),
    ]

    operations = [
        migrations.AlterField(
            model_name='location',
            name='address',
            field=models.CharField(blank=True, help_text='Full address, cross street, or partial address', max_length=254, verbose_name='address'),
        ),
        migrations.AlterField(
            model_name='location',
            name='county',
            field=models.ForeignKey(help_text='If county not on list <a href="/admin/supporting/county/add/" target="_blank">add it here</a>', on_delete=django.db.models.deletion.CASCADE, related_name='locations', related_query_name='location', to='supporting.county', verbose_name='county'),
        ),
    ]
