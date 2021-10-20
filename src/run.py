#!/usr/bin/python3

import os
import shelve
import subprocess
from re import findall
from zipfile import ZipFile
from urllib.request import urlopen, HTTPError, URLError

FAA_VFR_CHARTS_URL = 'https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/vfr/'
MIN_ZOOM = 0
MAX_ZOOM = 2

current_directory = os.path.dirname(__file__)
base_directory = os.path.abspath(os.path.join(current_directory, '..'))
tiles_directory = os.path.join(base_directory, 'tiles/')
tmp_directory = os.path.join(base_directory, 'tmp/')
assets_directory = os.path.join(base_directory, 'assets/')
clipping_shapes_directory = os.path.join(assets_directory, 'clipping_shapes/')
tilers_tools_directory = os.path.join(current_directory, 'tilers_tools')
raw_charts_directory = os.path.join(tmp_directory, '01_raw/')
colored_charts_directory = os.path.join(tmp_directory, '02_rgba/')
cropped_charts_directory = os.path.join(tmp_directory, '03_cropped/')
warped_charts_directory = os.path.join(tmp_directory, '04_warped/')
intermediate_tiles_directory = os.path.join(tmp_directory, '05_intermediate_tiles')
sectional_version_index_file = os.path.join(tmp_directory, 'version_index')
vrt_file = os.path.join(tmp_directory, 'merged_sectionals.vrt')


def run_command(command, print_output=False):
	if print_output:
			proc = subprocess.Popen(command, shell=True)
	else:
		proc = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	
	proc.communicate()


def create_directories():
	if not os.path.exists(tiles_directory):
		os.makedirs(tiles_directory)

	if not os.path.exists(tmp_directory):
		os.makedirs(tmp_directory)

	if not os.path.exists(raw_charts_directory):
		os.makedirs(raw_charts_directory)

	if not os.path.exists(colored_charts_directory):
		os.makedirs(colored_charts_directory)

	if not os.path.exists(cropped_charts_directory):
		os.makedirs(cropped_charts_directory)

	if not os.path.exists(warped_charts_directory):
		os.makedirs(warped_charts_directory)

	if not os.path.exists(intermediate_tiles_directory):
		os.makedirs(intermediate_tiles_directory)


def get_local_sectional_version(location):
	with shelve.open(sectional_version_index_file) as shelf:
		try:
			return shelf[location]
		except KeyError:
			return -1


def set_local_sectional_version(location, version):
	with shelve.open(sectional_version_index_file) as shelf:
		shelf[location] = version


def download_chart(sectional_info):
	try:
		with open(os.path.join(raw_charts_directory, sectional_info['location'] + '.zip'), 'wb') as zip_file:
			web_response = urlopen(sectional_info['url'])
			zip_file.write(web_response.read())

	except HTTPError as e:
		print('HTTP Error:' + e.code + sectional_info['url'])
	except URLError as e:
		print('URL Error:' + e.reason + sectional_info['url'])


def unzip_archive(archive_path, tif_name):
	previous_list = os.listdir(raw_charts_directory)
	
	if archive_path.endswith('.zip'):
		zip_ref = ZipFile(os.path.join(raw_charts_directory, archive_path), 'r')
		zip_ref.extractall(raw_charts_directory)
		zip_ref.close()
		os.remove(archive_path)
	
	new_files = [i for i in list(os.listdir(raw_charts_directory)) if i not in previous_list]

	for filename in new_files:
		if filename.endswith('.tif'):
			os.rename(
				os.path.join(raw_charts_directory, filename),
				os.path.join(raw_charts_directory, tif_name)
			)
		else:
			os.remove(
				os.path.join(raw_charts_directory, filename)
			)


def download_sectional_charts():
	print('Downloading new/updated sectional charts...')
	download_queue = list()
	web_response = urlopen(FAA_VFR_CHARTS_URL)
	web_content = str(web_response.read())
	matches = findall(r'="?(https?\:\/\/aeronav\.faa\.gov\/content\/aeronav\/sectional_files\/([a-zA-Z_\-]+)_([0-9]+)\.zip)"?>', web_content)

	for url, location, version in matches:
		sectional_info = {
			'url': str(url),
			'location': str(location),
			'version': int(version)
		}

		if sectional_info['location'] + '.tif' not in os.listdir(raw_charts_directory) or get_local_sectional_version(sectional_info['location']) < sectional_info['version']:
			for item in download_queue:
				if item['location'] == sectional_info['location'] and item['version'] < sectional_info['version']:
					item['url'] = sectional_info['url']
					item['version'] = sectional_info['version']
					break
			else:
				download_queue.append(sectional_info)

	# Iterate over each item in the download queue. The files in this queue are only the ones which are newer or simply missing
	for sectional_info in download_queue:
		print("Download: " + sectional_info['location'] + ", Version date: " + sectional_info['version'])

		# Remove TIFF files in processing directories. This is a fundamental part in the  mechanism to resume procssing after a halted run.
		run_command('rm -f ' + os.path.join(raw_charts_directory, sectional_info['location'] + '.tif'))
		run_command('rm -f ' + os.path.join(colored_charts_directory, sectional_info['location'] + '.tif'))
		run_command('rm -f ' + os.path.join(cropped_charts_directory, sectional_info['location'] + '.tif'))
		run_command('rm -f ' + os.path.join(warped_charts_directory, sectional_info['location'] + '.tif'))

		# Download the individual chart
		download_chart(sectional_info)

		# Write the sectional information to the index file
		set_local_sectional_version(sectional_info['location'], sectional_info['version'])

		# Unzip the sectional and delete the original zip file
		unzip_archive(os.path.join(raw_charts_directory, sectional_info['location'] + '.zip'), sectional_info['location'] + '.tif')


def expand_colors():
	print('Expanding chart colors to RGBA...')
	for filename in os.listdir(raw_charts_directory):
		if filename.endswith('.tif') and not os.path.exists(os.path.join(colored_charts_directory, filename)):
			run_command(
				'gdal_translate' + \
				' -expand rgba' + \
				' -of GTiff' + \
				' ' + os.path.join(raw_charts_directory, filename) + \
				' ' + os.path.join(colored_charts_directory, filename)
			)
			print('    Expanded colors for ' + os.path.splitext(filename)[0])


def crop_charts():
	print('Cropping charts to remove legend and border...')
	for filename in os.listdir(colored_charts_directory):
		if filename.endswith('.tif'):
			if 'Western_Aleutian_Islands' in filename and not os.path.exists(os.path.join(cropped_charts_directory, 'Western_Aleutian_Islands_East.tif')) and not os.path.exists(os.path.join(cropped_charts_directory, 'Western_Aleutian_Islands_West.tif')):
				run_command(
					'gdalwarp' + \
					' -dstnodata 0' + \
					' -q' + \
					' -cutline ' + os.path.join(clipping_shapes_directory, 'Western_Aleutian_Islands_East.shp') + \
					' -crop_to_cutline' + \
					' -of GTiff' + \
					' ' + os.path.join(colored_charts_directory, filename) + \
					' ' + os.path.join(cropped_charts_directory, 'Western_Aleutian_Islands_East.tif')
				)
				print('    Cropped Western_Aleutian_Islands_East')
				run_command(
					'gdalwarp' + \
					' -dstnodata 0' + \
					' -q' + \
					' -cutline ' + os.path.join(clipping_shapes_directory, 'Western_Aleutian_Islands_West.shp') + \
					' -crop_to_cutline' + \
					' -of GTiff' + \
					' ' + os.path.join(colored_charts_directory, filename) + \
					' ' + os.path.join(cropped_charts_directory, 'Western_Aleutian_Islands_West.tif')
				)
				print('    Cropped Western_Aleutian_Islands_West')
			elif 'Western_Aleutian_Islands' not in filename and not os.path.exists(os.path.join(cropped_charts_directory, filename)):
				run_command(
					'gdalwarp' + \
					' -dstnodata 0' + \
					' -q' + \
					' -cutline ' + os.path.join(clipping_shapes_directory, os.path.splitext(filename)[0] + '.shp') + \
					' -crop_to_cutline' + \
					' -of GTiff' + \
					' ' + os.path.join(colored_charts_directory, filename) + \
					' ' + os.path.join(cropped_charts_directory, filename)
				)
				print('    Cropped ' + os.path.splitext(filename)[0])


def warp_charts():
	print('Warping charts...')
	for filename in os.listdir(cropped_charts_directory):
		if filename.endswith('.tif') and not os.path.exists(os.path.join(warped_charts_directory, filename)):
			run_command(
				'gdalwarp' + \
				' -r lanczos' + \
				' -t_srs EPSG:4326' + \
				' ' + os.path.join(cropped_charts_directory, filename) + \
				' ' + os.path.join(warped_charts_directory, filename)
			)
			print('    Warped ' + os.path.splitext(filename)[0])


def create_leaflet_map_tiles():
	print('Creating map tiles...')

	# Remove any old map tiles
	run_command('rm -rf ' + os.path.join(tiles_directory, '!(example.html)'))
	run_command('rm -rf ' + os.path.join(intermediate_tiles_directory, '*'))

	# Create VRT file
	run_command('rm -f ' + vrt_file)
	run_command(
		'gdalbuildvrt' + \
		' ' + vrt_file + \
		' ' + os.path.join(warped_charts_directory, '*.tif')
	)

	# Create map tiles
	run_command(
		'python ' + os.path.join(tilers_tools_directory, 'gdal_tiler.py') + \
		' --profile=tms' + \
		' --release' + \
		' --paletted' + \
		' --zoom=' + ','.join([str(zoom_level) for zoom_level in range(MIN_ZOOM, MAX_ZOOM + 1)]) + \
		' --dest-dir=' + intermediate_tiles_directory + \
		' ' + vrt_file, True
	)

	# Move created map tiles to tiles directory
	for zoom_level in range(MIN_ZOOM, MAX_ZOOM + 1):
		run_command(
			'cp -R' + \
			' ' + os.path.join(intermediate_tiles_directory, os.path.splitext(os.path.basename(vrt_file))[0] + '.tms/' + str(zoom_level)) + \
			' ' + tiles_directory
		)


def main():
	create_directories()
	download_sectional_charts()
	expand_colors()
	crop_charts()
	warp_charts()
	create_leaflet_map_tiles()
	

if __name__ == "__main__":
   main()
