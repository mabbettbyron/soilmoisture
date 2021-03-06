# Generated by Django 3.0.6 on 2020-08-28 21:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('skeleton', '0021_reading_reviewed'),
    ]

    operations = [
        migrations.AddField(
            model_name='site',
            name='rz_percentage',
            field=models.FloatField(default=1, help_text='A percentage between 0 and 1 indicating total 7 day water use. A lower percentage from 100 indicates a smaller root stock.'),
        ),
        migrations.AddConstraint(
            model_name='site',
            constraint=models.CheckConstraint(check=models.Q(rz_percentage__gte=0), name='site_rz_percentage_gte_0'),
        ),
        migrations.AddConstraint(
            model_name='site',
            constraint=models.CheckConstraint(check=models.Q(rz_percentage__lte=1), name='site_rz_percentage_percentage_1te_1'),
        ),
    ]
