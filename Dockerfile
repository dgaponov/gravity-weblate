FROM weblate/weblate

USER root

COPY weblate_gravity /usr/src/weblate_gravity
RUN pip install --no-cache-dir /usr/src/weblate_gravity
ENV DJANGO_SETTINGS_MODULE=weblate_gravity.settings

EXPOSE 8080

USER 1000
