from django.http import HttpResponse
from django.template import loader

def first_graph(request, site_id):
    template = loader.get_template('graphs/first_graph.html')
    context = {}
    return HttpResponse(template.render(context, request))
