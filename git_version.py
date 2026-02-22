class gitlab_tools:
    def __init__(self, gitlab_access_token: str):
        self.log = logging.getLogger('log.' + self.__class__.__name__)
        self.gitlab_access_token = gitlab_access_token
        self.gitlab_url = "https://gitlab.radar.iil.intel.com"
        self.project_id = "2"
        self.headers = {"Private-Token": self.gitlab_access_token}
        self.gitlab_versions_url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/releases?tag_name="
        self.gitlab_releases_url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/releases"
        self.gitlab_packages_url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/packages/326/package_files"

    def get_bsr_release_versions(self):
        try:
            versions_list = []
            # Send GET request
            response = requests.get(self.gitlab_releases_url, headers=self.headers, verify=False)
            response.raise_for_status()  # Raise an exception for non-200 status codes

            # Parse JSON response
            releases = response.json()

            # Print release information (modify as needed)
            for release in releases:
                self.log.info(f"Release name: {release['name']}")
                self.log.info(f"Tag name: {release['tag_name']}")
                # self.log.info(f"Description: {release.get('description', 'No description provided')}")
                self.log.info("-" * 20)
                versions_list.append(release['tag_name'])
            return versions_list

        except requests.exceptions.RequestException as error:
            self.log.error(f"Error retrieving releases: {error}")

    def download_bsr_release_versions(self, dst: str = r'C:\temp\bsr_releases', version: str = 'v0.1.5', extract: bool = True):
        try:
            gitlab_versions_url = self.gitlab_versions_url + version
            # Send GET request
            response = requests.get(gitlab_versions_url, headers=self.headers, verify=False)
            response.raise_for_status()  # Raise an exception for non-200 status codes

            # Parse JSON response
            releases = response.json()

            # Check if release exists
            if not releases:
                self.log.info(f"Release with tag '{version}' not found.")

            # Get the first release (assuming you want the latest with that tag)
            release_index = [index for (index, item) in enumerate(releases) if version in item['name']]
            assert len(release_index) == 1, f'More then 1 or 0 version were found for version {version} ,  results:{str(release_index)}'
            release = releases[release_index[0]]

            # Extract asset information
            assets = release.get('assets', [])  # Handle potential absence of assets

            # Check if there are any assets
            if not assets:
                raise ValueError(f"Release '{release['name']}' has no downloadable assets.")

            # Download the first asset (assuming you want the first one)
            download_url = [x for x in assets['links'] if x['name'] == 'fw_updater_package'][0]['direct_asset_url']
            assert download_url is not [], f'Could not fins download link or version in {str(assets["links"])}'
            filename = os.path.join(dst, download_url.split('/')[-1])

            # Download the file using another request
            download_response = requests.get(download_url, headers=self.headers, stream=True, verify=False)
            download_response.raise_for_status()

            assert download_response.headers.get('content-length') != '0', f"Warning: Server responded with an empty file for '{download_url}'."
            if not os.path.exists(filename):
                # Open the file for writing in binary mode
                with open(filename, "wb") as f:
                    for chunk in download_response.iter_content(8192):
                        if chunk:  # filter out keep-alive new chunks
                            f.write(chunk)

            self.log.info(f"Downloaded asset: {filename}")
            dst = filename[:-7]
            if extract and not os.path.exists(dst):
                self.log.info(f"Extracting")
                if filename.endswith('.zip'):
                    with zipfile.ZipFile(filename, 'r') as zip_ref:
                        zip_ref.extractall(dst)
                    pass
                elif filename.endswith('.tar.gz'):
                    with tarfile.open(filename, 'r:gz') as tar_ref:
                        tar_ref.extractall(dst)
                elif filename.endswith('.tar.bz2'):
                    with tarfile.open(filename, 'r:bz2') as tar_bz2_ref:
                        tar_bz2_ref.extractall(dst)

                elif filename.endswith('.tar'):
                    with tarfile.open(filename, 'r') as tar_bz2_ref:
                        tar_bz2_ref.extractall(dst)
                else:
                    raise ValueError("Unsupported file format")
            return download_url.split('/')[-1]
        except requests.exceptions.RequestException as error:
            self.log.error(f"Error retrieving release or downloading asset: {error}")

    def download_bsr_nightly_versions(self, dst: str = r'C:\temp\bsr_releases', extract: bool = True):
        try:
            nightly_link_prefix = 'https://gitlab.radar.iil.intel.com/api/v4/projects/2/packages/generic/fw_updater_package/nightly/'
            # Send GET request
            # response = requests.get(self.gitlab_packages_url, headers=self.headers,params={'per_page': 100}, verify=False)
            # response.raise_for_status()  # Raise an exception for non-200 status codes


            # Parse JSON response
            # releases = response.json()
            releases=[]
            page = 1
            per_page = 100
            projects = []
            while True:
                # response = requests.get(self.gitlab_packages_url, headers=self.headers, params={'page': page, 'per_page': per_page}, verify=False)
                response = requests.get(self.gitlab_packages_url, headers=self.headers, params={'page': page}, verify=False)
                if response.status_code != 200:
                    print(f"Failed to fetch projects: {response.status_code}")
                    return []

                data = response.json()
                if not data:
                    break

                releases.extend(data)
                page += 1
            # Check if release exists
            if not releases:
                self.log.info(f"Release with tag not found.")
                exit(1)

            # Get the first release (assuming you want the latest with that tag)
            release_date = [date['created_at'] for date in releases]

            # Convert date strings to datetime objects
            parsed_dates = [datetime.fromisoformat(date_str) for date_str in release_date]

            # Get the latest date
            latest_date = max(parsed_dates)

            # Find the index of the latest date in the original list
            latest_index = parsed_dates.index(latest_date)

            download_url = nightly_link_prefix + releases[latest_index]['file_name']
            filename = os.path.join(dst, download_url.split('/')[-1])

            # Download the file using another request
            download_response = requests.get(download_url, headers=self.headers, stream=True, verify=False)
            download_response.raise_for_status()

            assert download_response.headers.get('content-length') != '0', f"Warning: Server responded with an empty file for '{download_url}'."
            if not os.path.exists(filename):
                # Open the file for writing in binary mode
                with open(filename, "wb") as f:
                    for chunk in download_response.iter_content(8192):
                        if chunk:  # filter out keep-alive new chunks
                            f.write(chunk)

                self.log.info(f"Downloaded asset: {filename}")
            dst = filename[:-7]
            if extract and not os.path.exists(dst):
                self.log.info(f"Extracting")
                if filename.endswith('.zip'):
                    with zipfile.ZipFile(filename, 'r') as zip_ref:
                        zip_ref.extractall(dst)
                    pass
                elif filename.endswith('.tar.gz'):
                    with tarfile.open(filename, 'r:gz') as tar_ref:
                        tar_ref.extractall(dst)
                elif filename.endswith('.tar.bz2'):
                    with tarfile.open(filename, 'r:bz2') as tar_bz2_ref:
                        tar_bz2_ref.extractall(dst)

                elif filename.endswith('.tar'):
                    with tarfile.open(filename, 'r') as tar_bz2_ref:
                        tar_bz2_ref.extractall(dst)
                else:
                    raise ValueError("Unsupported file format")

            return download_url.split('/')[-1]

        except requests.exceptions.RequestException as error:
            self.log.error(f"Error retrieving release or downloading asset: {error}")

    def download_bsr_ci_version(self, dst: str = r'C:\tmp\bsr_releases', version: str = 'v0.1.5', extract: bool = True):
        if version is None:
            self.download_bsr_nightly_versions(dst=dst, extract=extract)
        else:
            self.download_bsr_release_versions(dst=dst, version=version, extract=extract)

