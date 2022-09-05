import argparse
import json
import os


def create_courses_json():
    # Ensure input
    parser = argparse.ArgumentParser()
    parser.add_argument('course_file_directory')
    parser.add_argument('output_file_dir')
    parser.add_argument('output_year')
    parser.add_argument('collected_file_year')
    parser.add_argument('semester')
    args = parser.parse_args()

    file_list = os.listdir(args.course_file_directory)
    semester_number = '1' if args.semester == 'a' else '2'
    filtered_file_list = [file_name
                          for file_name in file_list
                          if file_name.endswith(f'{args.collected_file_year}_{semester_number}.txt')]
    output_file_path = os.path.join(args.output_file_dir, f'courses_{args.output_year}0{semester_number}.min.js')
    all_courses = []
    for course_file_name in filtered_file_list:
        course_file_path = os.path.join(args.course_file_directory, course_file_name)
        with open(course_file_path, 'r') as f:
            all_courses.append(json.load(f))

    js_variable = f'var courses_from_rishum = {json.dumps(all_courses, ensure_ascii=False)}'

    with open(output_file_path, 'w') as f:
        f.write(js_variable)


if __name__ == '__main__':
    create_courses_json()
