import argparse
import asyncio
import json
import logging
import os
from typing import List, Dict, Set

from hujiscrape.fetchers import Fetcher
from hujiscrape.huji_objects import Course
from hujiscrape.magics import Semester
from hujiscrape.scrapers import SingleCourseScraper

DEFAULT_CONCURRENT_REQUESTS = 100


def hujiscrape_course_to_cheese(course: Course, semester: Semester) -> Dict:
    course_general_dict = {
        "אחראים": "",  # Currently not shown in the Shnaton (will be added when adding the Syllabus)
        "הערות": course.hebrew_notes,
        "הרצאה": "2",
        "מספר מקצוע": course.course_id,
        "מעבדה": "0",
        "מקצועות ללא זיכוי נוסף": "",
        "מקצועות קדם": "",
        "נקודות": str(course.credits),
        "סילבוס": course.syllabus_url,
        "סמינר/פרויקט": "0",
        "פקולטה": course.faculty,
        "שם מקצוע": course.hebrew_name,
        "תרגיל": "2"
    }

    # Add exams if they exist. Only take the last relevant one (e.g. in course 67506)
    for exam in (course.exams or []):

        # Only look at correct semester.
        # Note: only allowing "semester" to be in A and B.
        if Semester.from_hebrew(exam.semester) != semester:
            continue

        if "א'" in exam.moed:
            course_general_dict['מועד א'] = f"בתאריך {exam.date.replace('-', '.')} יום ה"

        if "ב'" in exam.moed:
            course_general_dict['מועד ב'] = f"בתאריך {exam.date.replace('-', '.')} יום ה"

    course_schedule = []
    for lesson in course.schedule:
        try:
            lesson_semester = Semester.from_hebrew(lesson.semester)
        except ValueError:
            logging.info(f"Invalid semester for course {course.course_id}: {lesson.semester}. Skipping lesson.")
            continue

        # Only add lessons in the requested semester or yearly lessons
        if lesson_semester != semester and lesson_semester != Semester.Yearly:
            continue

        # If there are lessons without a day/time don't record them
        if not lesson.time or not lesson.day:
            continue

        from_hour, to_hour = lesson.time.split('-')

        if lesson.day == '':
            continue

        lesson_dict = {
            "מרצה/מתרגל": "\t".join(lesson.lecturers),
            "קבוצה": lesson.group,
            "מס.": str(lesson.row),
            "סוג": lesson.type,
            "בניין": lesson.location,
            "חדר": "",
            "שעה": f'{to_hour} - {from_hour}',
            "יום": lesson.day[-2]  # The day format is "יום א'", so taking the letter
        }
        course_schedule.append(lesson_dict)

    return {'general': course_general_dict, 'schedule': course_schedule}


async def collect_by_id(
        course_ids: List[int | str],
        year: int,
        include_exams: bool = True,
        concurrent_requests: int = DEFAULT_CONCURRENT_REQUESTS,
        show_progress: bool = True,
        fail_after_n_missing_courses: int = 0,
        close_tcp_after_request: bool = False
) -> List[Course]:
    """

    :param course_ids: List of course ids to scrape
    :param year: year to scrape
    :param include_exams: should the exams be scraped as well
    :param concurrent_requests: number of concurrent requests
    :param show_progress: should a progress bar be shown
    :param fail_after_n_missing_courses: if more than n courses are missing, raise an exception.
                                         if 0, do not raise an exception
    :param close_tcp_after_request: should the TCP connection be closed after each request.
                                    this can help avoid some exceptions that can occur with the scraping.
    :return:
    """
    scraper = SingleCourseScraper(
            fetcher=Fetcher(max_concurrency=concurrent_requests, tcp_socket_limit=20,
                            force_close_tcp=close_tcp_after_request),
    )
    return await scraper.scrape(
        course_ids=course_ids,
        year=year,
        include_exams=include_exams,
        show_progress=show_progress,
        fail_after_n_missing_courses=fail_after_n_missing_courses
    )


def prepare_cheese_format(courses: List[Course], semester: Semester) -> str:
    cheese_courses: List[Dict] = []
    existing_course_ids: Set[str] = set()
    for course in courses:
        try:
            course_semester = Semester.from_hebrew(course.semester)
        except ValueError:
            logging.warning(f"Invalid course semester for %s. Skipping course...", course.course_id)
            continue

        # Dedup the course
        if course.course_id in existing_course_ids:
            continue

        # Course must be running this year
        if not course.is_running:
            continue

        # Check that the course matches the semester required.
        if semester == Semester.A and course_semester not in (Semester.A, Semester.AB, Semester.Yearly):
            continue
        if semester == Semester.B and course_semester not in (Semester.B, Semester.AB, Semester.Yearly):
            continue

        existing_course_ids.add(course.course_id)
        try:
            cheese_courses.append(
                hujiscrape_course_to_cheese(course, semester)
            )
        except Exception:
            logging.warning("Failed to convert course %s", course.course_id)
            raise

    return f'var courses_from_rishum = {json.dumps(cheese_courses, ensure_ascii=False)}'


async def main():
    parser = argparse.ArgumentParser()

    def add_common_args_to_parser(p: argparse.ArgumentParser):
        p.add_argument('-y', '--year', type=int, required=True, help="Academic year to process.")
        p.add_argument('-r', '--concurrent-requests', default=DEFAULT_CONCURRENT_REQUESTS, type=int,
                            help="Number of concurrent requests.")
        p.add_argument('-t', '--close-tcp-after-request', action='store_true',
                            help="Close the TCP connection after each request. This slows down the scraping but can "
                                 "help avoid some exceptions that can occur with the scraping.")
        p.add_argument('-v', '--verbose', action='store_true', help="Enable verbose output.")


    subparsers = parser.add_subparsers(dest="mode", required=True)

    # Subparser for "list" mode (no additional arguments required)
    list_parser = subparsers.add_parser("list",
                                        help="Output a list of course numbers that exist in the specified year.")
    list_parser.add_argument("--min", type=int, default=1, help="Minimum course number to look for.")
    list_parser.add_argument("--max", type=int, default=100000, help="Maximum course number to look for.")
    list_parser.add_argument('-o', '--output-file', type=str, required=True, help="Output file to save results.")
    add_common_args_to_parser(list_parser)

    # Subparser for "scrape" mode (requires additional arguments)
    scrape_parser = subparsers.add_parser("scrape",
                                          help="Scrape course data for specific courses and save results.")
    scrape_parser.add_argument('-c', '--courses', nargs='+', help="List of course numbers to scrape.")
    scrape_parser.add_argument('-f', '--course_file', help="File with all the courses delimited by line breaks.")
    scrape_parser.add_argument('-o', '--output-dir', type=str, help="Output directory to save results.",
                               default=os.path.join('.', 'deploy', 'courses'))
    scrape_parser.add_argument('-n', '--fail-after-n-missing-courses', type=int, default=0,
                               help="Fail after n courses that weren't scraped fetched correctly. "
                                    "This is helpful to detect general failures, or single course failures.")
    add_common_args_to_parser(scrape_parser)

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO)

    if args.mode == "list":
        courses = await collect_by_id(
            course_ids=list(range(args.min, args.max + 1)),
            year=args.year,
            include_exams=False,
            concurrent_requests=args.concurrent_requests,
            show_progress=True,
            close_tcp_after_request=args.close_tcp_after_request
        )
        with open(args.output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(sorted([course.course_id for course in courses], key=lambda x: int(x))))
        return

    if args.mode == "scrape":

        courses_to_scrape = []
        if args.courses:
            courses_to_scrape += args.courses

        if args.course_file:
            with open(args.course_file, 'r') as f:
                course_ids = [line for line in f.read().split('\n') if line]
                courses_to_scrape += course_ids

        courses = await collect_by_id(
            course_ids=[int(course_id) for course_id in courses_to_scrape],
            year=args.year,
            include_exams=True,
            concurrent_requests=args.concurrent_requests,
            show_progress=True,
            fail_after_n_missing_courses=args.fail_after_n_missing_courses,
            close_tcp_after_request=args.close_tcp_after_request,
        )

        for idx, semester in enumerate([Semester.A, Semester.B]):
            js_variable = prepare_cheese_format(courses, semester)
            # Year is always one less in cheesefork than it is in the shnaton
            filename = f'courses_{args.year - 1}{idx + 1:02}.min.js'
            with open(os.path.join(args.output_dir, filename), 'w', encoding='utf-8') as f:
                f.write(js_variable)


if __name__ == '__main__':
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
