from photo_organizer import organize_photos

if __name__ == "__main__":
    # Example usage — edit these paths to point at your own photo directories.
    source_directory = r"D:\Photos From My Phone\iPhone 12"
    destination_directory = r"D:\Photos From My Phone\iPhone 12 Reorg"
    organize_photos(source_directory, destination_directory)
