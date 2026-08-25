import os
from setuptools import find_packages, setup

with open(os.path.join(os.path.dirname(__file__), 'README.md')) as readme:
    README = readme.read()

os.chdir(os.path.normpath(os.path.join(os.path.abspath(__file__), os.pardir)))

setup(
    name='openimis-be-zm_etl_zispis',
    version='0.1.0',
    packages=find_packages(),
    include_package_data=True,
    license='GNU AGPL v3',
    description='Zambia Social Registry - ZISPIS ETL connector.',
    long_description=README,
    long_description_content_type='text/markdown',
    url='https://github.com/etsebo-zm-nsr',
    install_requires=[
        'django',
        'openimis-be-core',
        'openimis-be-individual',
        'openimis-be-api_etl',
    ],
    classifiers=[
        'Environment :: Web Environment',
        'Framework :: Django',
        'License :: OSI Approved :: GNU Affero General Public License v3',
        'Programming Language :: Python :: 3.11',
    ],
)
