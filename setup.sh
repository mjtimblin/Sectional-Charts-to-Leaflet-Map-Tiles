#!/bin/bash

sudo apt-get update

sudo apt-get install -y --no-install-recommends \
	build-essential \
	gdal-bin \
	python-dev \
	python3-dev \
	python-gdal \
	python3-pip
