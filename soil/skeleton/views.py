from django.http import HttpResponse
from django.template import loader
from django.views.generic import TemplateView, ListView, View, CreateView
from django.utils import timezone
from django.core import management

from django.shortcuts import render, get_object_or_404, redirect
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.contrib import messages

from django.db.models import Sum
from .models import Probe, Reading, Site, Season, SeasonStartEnd, CriticalDate, CriticalDateType
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin

import re
import requests

# Get an instance of a logger
import logging
logger = logging.getLogger(__name__)

from .forms import DocumentForm, SiteReadingsForm, SeasonStartEndForm

from datetime import datetime

from .utils import get_site_season_start_end, process_probe_data, process_irrigation_data

def index(request):
    template = loader.get_template('index.html')
    try:
        if request.method == 'POST':
            logger.debug(request.POST)
            button_clicked = request.POST['button']
            logger.info('button ' + str(button_clicked))
            if button_clicked == 'processrootzones':
                management.call_command('processrootzones')
            if button_clicked == 'processmeter':
                management.call_command('processmeter')
            if button_clicked == 'processdailywateruse':
                management.call_command('processdailywateruse')
            if button_clicked == 'processrain':
                management.call_command('processrain')
            if button_clicked == 'processall':
                management.call_command('processall_readings')
            messages.success(request, "Successfully ran process: " + str(button_clicked))
    except Exception as e:
        messages.error(request, "Error: " + str(e))
    return render(request, 'index.html', {})

def seasonstartend(request):

    try:
        if request.method == 'POST':
            form = SeasonStartEndForm(request.POST)
            logger.debug(request.POST)

            # for a crop and region get all of those sites
            region = request.POST['region']
            crop = request.POST['crop']
            season = request.POST['season']
            sites = Site.objects.filter(farm__address__locality__state=region, crop=crop)
            # create a couple of start and end critical date critical_date_types
            start_type = CriticalDateType.objects.get(name='Start')
            end_type = CriticalDateType.objects.get(name='End')
            current_user = request.user
            for site in sites:
                # If we don't already have a season start end we insert, we don't update and existing one
                exists = SeasonStartEnd.objects.filter(site=site.id, season=season).count()
                logger.debug(site.name + " has " + str(exists))
                if exists:
                    logger.debug('Not updating')
                else:
                    cd = CriticalDate(
                        site = site,
                        season_id = season,
                        date = request.POST['period_from'],
                        type = start_type,
                        created_by = current_user
                    )
                    cd.save()
                    cd = CriticalDate(
                        site = site,
                        season_id = season,
                        date = request.POST['period_to'],
                        type = end_type,
                        created_by = current_user
                    )
                    cd.save()
                    logger.debug('Inserting Season start end records')
            return redirect('seasonstartend')
        else:
            form = SeasonStartEndForm()
    except Exception as e:
        messages.error(request, "Error: " + str(e))
    return render(request, 'season_start_end.html', {
        'form': form,
    })

#TODO why CreateView and not Template View
class SiteReadingsView(LoginRequiredMixin, CreateView):
    model = Reading
    form_class = SiteReadingsForm
    template_name = 'site_readings.html'

def load_graph(request):
    site_id = request.GET.get('site')
    season_id = request.GET.get('season')
    context = None

    try:
        site = Site.objects.get(id=site_id)
        season = Season.objects.get(id=season_id)
        dates = get_site_season_start_end(site, season)

        readings = Reading.objects.filter(site=site.id, date__range=(dates.period_from, dates.period_to)).order_by('-date')
        logger.info(str(readings))
        try:
            latest = readings[0].date
        except:
            raise Exception("No Reading for Site and Season")
        try:
            previous = readings[1].date
        except:
            raise Exception("No Previous Reading for Site and Season")
        logger.debug("Date:" + str(latest))
        logger.debug("Previous:" + str(previous))

        context = {
            'site_id' : site_id,
            'date' : latest,
            'previous': previous,
            'period_to': dates.period_to,
        }
    except Exception as e:
        messages.error(request, "Error with Loading Graph: " + str(e))
    return render(request, 'vsw_percentage.html', context)

def load_sites(request):
    technician_id = request.GET.get('technician')
    sites = Site.objects.filter(technician_id=technician_id).order_by('name')
    return render(request, 'site_dropdown_list_options.html', {'sites':sites})

def load_site_readings(request):
    readings = None
    comment = ''
    rainfall_total = 0
    irrigation_total = 0

    try:
        site_id = request.GET.get('site')
        season_id = request.GET.get('season')

        if site_id:
            try:
                dates = SeasonStartEnd.objects.get(site=site_id, season=season_id)
            except:
                raise Exception("No Season Start and End set up for site.")

            readings = Reading.objects.filter(site__seasonstartend__site=site_id, site__seasonstartend__season=season_id, date__range=(dates.period_from, dates.period_to)).order_by('date')
            c = readings.filter().last()
            comment = c.comment

            # Total Rainfall and irrigation
            rainfall_total = readings.aggregate(Sum('rain'))
            irrigation_total = readings.aggregate(Sum('irrigation_litres'))
    except Exception as e:
        messages.error(request, " Error is: " + str(e))
    return render(request, 'site_readings_list.html', {
        'readings' : readings,
        'comment' : comment,
        'rainfall' : rainfall_total,
        'irrigation' : irrigation_total,
    })

'''
    For a particular site, season and date find the previous reading date
'''
def get_irrigation_litres(readingqs):
    logger.info("Date:" + get_previous_date_season)


@login_required
def vsw_percentage(request, site_id, year, month, day):
    template = loader.get_template('vsw_percentage.html')
    context = {
        'site_id' : site_id,
        'year' : year,
        'month' : month,
        'day': day
    }
    return HttpResponse(template.render(context, request))

'''
    model_form_upload - For processing Probe and Diviner files
'''

@login_required
def model_form_upload(request):
    data = {}
    if request.method == 'POST':
        form = DocumentForm(request.POST, request.FILES)
        logger.debug(request.POST)
        files = request.FILES.getlist('document')

        if form.is_valid():
            for f in files:
                logger.info('***Saving File:' + str(f))
                form.save()
                try:
                    handle_file(f, request)
                    messages.success(request, "Successfully Uploaded file: " + str(f))
                except Exception as e:
                    messages.info(request, "info with file: " + str(f) + " info is: " + str(e))
            return redirect('model_upload')
        else:
            logger.info('***Form not valid:' + str(form))
    else:
        form = DocumentForm()
    return render(request, 'model_form_upload.html', {
        'form': form,
    })

'''
    handle_file - Generic file handler to create a data file as it is uploaded through a web form
'''

def handle_file(f, request):
    # File saved. Now try and process it
    logger.debug('***Processing File:' + str(f))
    type = request.POST['filetype']

    file_data = ""
    try:
        for chunk in f.chunks():
            file_data = file_data + chunk.decode("utf-8")
    except Exception as e:
        logger.info(e)
    finally:
        # Call different handlers
        if type == 'neutron':
            handle_neutron_file(file_data, request)
        elif type == 'diviner':
            handle_diviner_file(file_data, request)
        else:
            handle_prwin_file(file_data, request)
'''
    handle_neutron_file
'''

def handle_neutron_file(file_data, request):
    logger.debug("***Handling Neutron")
    # process
    lines = file_data.split("\n")
    logger.info("Serial Line:" + lines[1])
    serialfields = lines[1].split(",")
    serialnumber = serialfields[1]
    serialnumber_formatted = serialnumber.lstrip("0")
    logger.info("Serial Number:" + serialnumber_formatted)

    # Check Serial Number exists and return info message if is not. Then get the serial number unique id
    if not Probe.objects.filter(serial_number=serialnumber_formatted).exists():
        raise Exception("Serial Number:" + serialnumber_formatted + " does not exist.")
    p = Probe.objects.get(serial_number=serialnumber_formatted)
    serial_number_id = p.id

    # Variable for loop
    data = {}
    date_formatted = None
    site_number = None
    readings = []

    for line in lines:
        # If Note, grab the site_id
        note = re.search("^Note,[a-zA-Z0-9_]+", line)
        reading = re.search("^\d.*", line)
        if note:
            logger.debug("***We have a note line:" + line)
            # If not first note line of file
            if any(data):
                readings.reverse() # Neutron Probe files go from deepest to shallowest
                data[key].append(readings)
                readings = []
            site_line = line.split(",")
            site_number = site_line[1].rstrip()
            logger.info("Site Number:" + str(site_number))
        elif reading:
            logger.info("***We have a reading line:" + line)
            reading_line = line.split(",")
            # If first reading for note, we need to get the date and create the key
            if reading_line[0] == "1":
                # Get date part from first depth is fine. Comes in as DD/MM/YY American crap format before we get underscore time component
                date_raw = str(reading_line[10])
                datefields = date_raw.split("_")
                date = datefields[0]
                date_object = datetime.strptime(date, '%m/%d/%y') # American
                date_formatted = date_object.strftime('%Y-%m-%d')

                key = site_number.rstrip() + "," + date_formatted
                logger.info("Key:" + key)

                if key in data:
                    logger.info("Key exists:")
                else:
                    logger.info("No Key does not exist:")
                    data[key] = []

            readings.append(float(reading_line[6]))
        else:
            logger.info("Else not valid processing line!"  + line)

    data[key].append(readings) # Always insert last reading
    logger.info("Final Data submitted to process_probe_data:" + str(data))
    process_probe_data(data, serial_number_id, request)

'''
    handle_diviner_file
'''

def handle_diviner_file(file_data, request):
    logger.info("***Handling Diviner")
    lines = file_data.split("\n")

    # Variable for loop
    data = {}
    date_formatted = None
    site_number = None
    serial_number_id = None
    readings = []
    need_date = True

    for line in lines:
        # Site Heading line contains the special Diviner Number
        heading = re.search("^Site.*", line)
        # Seems that a reading line is the only one beginning with a number (day part of date)
        reading = re.search("^\d.*", line)

        if heading:
            logger.info("***We have a heading line:" + line)
            diviner_fields = line.split(",")
            diviner_number = diviner_fields[1]
            diviner_number_formatted = diviner_number.lstrip()
            logger.info("Diviner Number Formatted:" + diviner_number_formatted)

            # Get Serial Number and Site Number from Diviner Probe and
            try:
                site = Site.objects.get(diviner__diviner_number=int(diviner_number_formatted))
            except:
                raise Exception("Diviner Number:" + diviner_number_formatted + " not set up for a site.")
            site_number = site.site_number
            logger.info("Site Number:" + site_number)

            try:
                sn = Probe.objects.get(probediviner__diviner__diviner_number=int(diviner_number_formatted))
            except:
                raise Exception("Diviner Number:" + diviner_number_formatted + " not set up for a probe/serial number.")
            serial_number_id = sn.id
            logger.info("Serial Number ID:" + str(serial_number_id))

        elif reading:
            logger.info("***We have a reading line:" + line)
            reading_line = line.split(",")

            if need_date:
                # Handle date in dd Month YYYY 24HH:MM:SS format
                date_raw = str(reading_line[0])
                date_object = datetime.strptime(date_raw, '%d %b %Y %H:%M:%S')
                date_formatted = date_object.strftime('%Y-%m-%d')
                logger.info("Date:" + date_formatted)
                key = site_number + "," + date_formatted
                logger.info("Key:" + key)
                data[key] = []
                need_date = False

            # Always remove date as the first element
            reading_line.pop(0)
            logger.info(reading_line)
            reading_array = []
            for reading in reading_line:
                reading = reading.lstrip(' ')
                reading = reading.rstrip()
                reading_array.append(float(reading))

            data[key].append(reading_array)
        else:
            logger.info("Not a line to process:"  + line)

    logger.info("Final Data:" + str(data))
    process_probe_data(data, serial_number_id, request)

'''
    handle_prwin_file
'''

def handle_prwin_file(file_data, request):
    logger.debug("***Handling PRWIN")
    lines = file_data.split("\n")

    # Use first line to get position of serial number (SN). Between serial number and field 3 (date) will be counts (up to 10)
    logger.debug("***Line 1 is " + str(lines[0]))
    header = lines[0].split(",")
    sn_index = header.index('SN')
    logger.info("SN Index:" + str(sn_index))
    del lines[0]

    data = {}
    irrigation_data = {}
    site_number = None
    serial_number_id = None
    bolNeedSerialNumber = True

    for line in lines:
        reading = re.search("^\d.*", line) # Make sure we have a reading line
        if reading:

            fields = line.split(",")

            # First field of every line is site number
            site_number = fields[0]
            logger.info("Site Number:" + site_number)
            reading_type = fields[1]
            logger.info("Type:" + reading_type)

            # We only want 'Probe' reading types
            if reading_type == 'Probe':
                # Get date part. Comes in as DD/MM/YYYY before we get 'space character' time component
                date_raw = str(fields[2])
                datefields = date_raw.split(" ")
                date = datefields[0]
                date_object = datetime.strptime(date, '%d/%m/%Y') # American
                date_formatted = date_object.strftime('%Y-%m-%d')
                logger.info("Date:" + date_formatted)

                # Get Serial Number. We are just going to get it once and asume all PRWIN readings for the season are from one probe
                if bolNeedSerialNumber:
                    serialnumber = fields[sn_index]
                    logger.info("Serial Number:" + serialnumber)
                    serialnumber = int(serialnumber)
                    # Check Serial Number exists and return info message if is not. Then get the serial number unique id
                    if not Probe.objects.filter(serial_number=serialnumber).exists():
                        raise Exception("Serial Number:" + serialnumber + " does not exist.")
                    p = Probe.objects.get(serial_number=serialnumber)
                    serial_number_id = p.id
                    bolNeedSerialNumber = False

                # Create Key
                key = site_number + "," + date_formatted
                logger.info("Key:" + key)

                reading_array = []
                irrigation_array = []
                data[key] = []
                irrigation_data[key] = []

                for depth in range(3, sn_index):
                    reading = float(fields[depth])
                    logger.info("Reading:" + str(reading))
                    reading_array.append(reading)

                #logger.info("Reading Array:" + str(reading_array))

                # Wierldy enough we make 3 of these arrays to put in data to match nuetron and diviner
                for lap in range(3):
                    data[key].append(reading_array)

                # For PRWIN files we also upload other readings data (already been derived from counts)
                # (SN), 0-100 cm (rz1),0-70 cm (rz2),0-45 cm (rz3),Deficit,ProbeDWU (probe_dwu),EstimatedDWU (estimated_dwu),
                # Rain,Meter,Irrigation(L) (irrigation_litres),Irrigation(mm) (irrigation_litres_mms) ,EffRain1 (effective_rain_1),
                # Effective Rainfall (effective_rainfall) ,EffIrr1 (efflrr1),EffIrr2 (efflrr1), Effective Irrigation (effective_irrigation)

                for value in range(sn_index + 1, sn_index + 16):
                    irrigation = 0.0
                    if fields[value]:
                        irrigation = float(fields[value])
                    logger.info("Irrigation:" + str(irrigation))
                    irrigation_array.append(irrigation)
                irrigation_data[key] = irrigation_array

        # End if we have a reading
    # End loop through lines

    #logger.info("Final Data:" + str(data))
    logger.info("irrir array" + str(irrigation_data))
    process_probe_data(data, serial_number_id, request)
    process_irrigation_data(irrigation_data, serial_number_id, request)
