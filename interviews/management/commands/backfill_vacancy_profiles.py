from django.core.management.base import BaseCommand
from interviews.models import InterviewSession, VacancyProfile


class Command(BaseCommand):
    help = 'Backfill VacancyProfile for sessions created before migration 0004'

    def handle(self, *args, **options):
        sessions = InterviewSession.objects.filter(
            vacancy_profile__isnull=True
        ).select_related('user').order_by('created_at')

        total = sessions.count()
        if not total:
            self.stdout.write('Nothing to backfill.')
            return

        self.stdout.write(f'Found {total} session(s) without vacancy_profile.')
        updated = 0

        for session in sessions:
            profile, created = VacancyProfile.objects.get_or_create(
                user=session.user,
                vacancy_text=session.vacancy_text,
                defaults={
                    'job_title': session.job_title,
                    'company_name': session.company_name,
                },
            )
            if not created and (session.job_title or session.company_name):
                profile.job_title = session.job_title
                profile.company_name = session.company_name
                profile.save(update_fields=['job_title', 'company_name'])

            session.vacancy_profile = profile
            session.save(update_fields=['vacancy_profile'])
            updated += 1
            self.stdout.write(
                f'  Session {session.id} ({session.user.username}) → '
                f'VacancyProfile {profile.id} ({"created" if created else "existing"})'
            )

        self.stdout.write(self.style.SUCCESS(f'Done. Updated {updated} session(s).'))