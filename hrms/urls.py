from django.contrib import admin
from django.urls import path, include


# Custom error handlers
handler404 = 'core.views.error_404'
handler500 = 'core.views.error_500'
handler403 = 'core.views.error_403'
handler400 = 'core.views.error_400'


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),  # Make sure your app name is 'core'
]



# ─── Static & media files (local development only) ───
from django.conf import settings
from django.conf.urls.static import static

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    