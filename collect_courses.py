import argparse
import asyncio
import csv
import json
import logging
import os
from typing import List, Dict, Set

from hujiscrape import ShnatonCourseScraper, Course, Semester, Toar, ToarYear, MaslulAllPageScraper


def hujiscrape_course_to_cheese(course: Course, semester: Semester) -> Dict:
    course_general_dict = {
        "אחראים": "",  # Currently not shown in the Shnaton (will be added when adding the Syllabus)
        "הערות": course.hebrew_notes,
        "הרצאה": "2",
        "מספר מקצוע": course.course_id,
        "מעבדה": "0",
        "מקצועות ללא זיכוי נוסף": "",
        "מקצועות קדם": "",
        "נקודות": str(course.points),
        "סילבוס": "",
        "סמינר/פרויקט": "0",
        "פקולטה": course.faculty,
        "שם מקצוע": course.hebrew_name,
        "תרגיל": "2"
    }

    # Add exams if they exist. Only take the last relevant one (e.g. in course 67506)
    for exam in course.exams:
        # Only look at correct semester.
        # Note: only allowing "semester" to be in A and B.
        if exam.semester != semester:
            continue

        if "א'" in exam.moed:
            course_general_dict['מועד א'] = f"בתאריך {exam.date.replace('-', '.')} יום ה"

        if "ב'" in exam.moed:
            course_general_dict['מועד ב'] = f"בתאריך {exam.date.replace('-', '.')} יום ה"

    course_schedule = []
    for lesson in course.schedule:
        # Only add lessons in the requested semester or yearly lessons
        if lesson.semester != semester and lesson.semester != Semester.Yearly:
            continue

        # If there are lessons without a day/time don't record them
        if not lesson.time or not lesson.day:
            continue

        from_hour, to_hour = lesson.time.split('-')
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


async def collect_by_id(course_ids: List[str], year: int) -> List[Course]:
    async with ShnatonCourseScraper(course_ids, year, concurrent_requests=20) as scraper:
        return await scraper.scrape()


async def collect_maslul(year: int, faculty: str, hug: str, maslul: str, toar: Toar = None,
                         toar_year: ToarYear = None) -> List[Course]:
    async with MaslulAllPageScraper(year, faculty, hug, maslul, toar, toar_year, concurrent_requests=20) as scraper:
        return await scraper.scrape()


def prepare_cheese_format(courses: List[Course], semester: Semester) -> str:
    cheese_courses: List[Dict] = []
    existing_course_ids: Set[str] = set()
    for course in courses:

        # Dedup the course
        if course.course_id in existing_course_ids:
            continue

        # Course must be running this year
        if not course.is_running:
            continue

        # Check that the course matches the semester required.
        if semester == Semester.A and course.semester not in (Semester.A, Semester.AB, Semester.Yearly):
            continue
        if semester == Semester.B and course.semester not in (Semester.B, Semester.AB, Semester.Yearly):
            continue

        existing_course_ids.add(course.course_id)
        cheese_courses.append(
            hujiscrape_course_to_cheese(course, semester)
        )

    return f'var courses_from_rishum = {json.dumps(cheese_courses, ensure_ascii=False)}'


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--courses', nargs='+')
    parser.add_argument('-f', '--course_file', help="File with all the courses delimited by line breaks.")
    parser.add_argument('-y', '--year', type=int, required=True)
    parser.add_argument('-m', '--maslul-csv', help="File with all the masluls to download. "
                                                   "Should be specified in a csv without headers, in the format:"
                                                   "<faculty>,<hug>,<maslul>,<toar>,<toar_year>.")
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-o', '--output-file', type=str, required=True)
    # TODO: currently only support A and B semesters (not summer)
    parser.add_argument('-s', '--semester', choices=[Semester.A, Semester.B],
                        type=Semester.__getitem__, required=True)
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO)

    scrape_coros = []
    if args.courses:
        scrape_coros.append(collect_by_id(args.courses, args.year))

    if args.course_file:
        with open(args.course_file, 'r') as f:
            course_ids = [line for line in f.read().split('\n') if line]
            scrape_coros.append(collect_by_id(course_ids, args.year))

    if args.maslul_csv:
        with open(args.maslul_csv, 'r') as f:
            for row in csv.reader(f):
                faculty, hug, maslul, toar, toar_year = row
                toar = Toar[toar]
                toar_year = ToarYear[toar_year]
                scrape_coros.append(collect_maslul(args.year, faculty, hug, maslul, toar, toar_year))

    course_list_list: List[List[Course]] = await asyncio.gather(*scrape_coros)
    courses = [course for course_list in course_list_list for course in course_list]
    js_variable = prepare_cheese_format(courses, args.semester)
    with open(args.output_file, 'w') as f:
        f.write(js_variable)


if __name__ == '__main__':
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
