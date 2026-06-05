import os.path
import io
import time
import socket
import qrcode
from datetime import datetime
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import threading

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]



def has_internet_connection(timeout=3):
  """Return True when the machine can reach the internet."""
  try:
    socket.create_connection(("8.8.8.8", 53), timeout=timeout).close()
    return True
  except OSError:
    return False



def find_or_create_folder(service, folder_name):
  """Find or create a folder in Google Drive."""
  try:
    # Search for the folder
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    items = results.get('files', [])
    
    if items:
      return items[0]['id']
    else:
      # Create the folder
      file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder'
      }
      folder = service.files().create(body=file_metadata, fields='id').execute()
      return folder.get('id')
  except HttpError as error:
    print(f"An error occurred while finding/creating folder: {error}")
    return None


def upload_file_to_drive(service, file_path, folder_id, progress_callback=None, status_callback=None):
  """Upload a file to Google Drive."""
  try:
    if not os.path.exists(file_path):
      if status_callback:
        status_callback(f"Error: File '{file_path}' does not exist.")
      return None
    
    file_name = os.path.basename(file_path)
    if status_callback:
      status_callback(f"Uploading '{file_name}' to Google Drive...")
    
    file_metadata = {
      'name': file_name,
      'parents': [folder_id]
    }
    
    # Set chunk size to 256KB for better progress visibility
    media = MediaFileUpload(file_path, mimetype='application/pdf', resumable=True, chunksize=262144)
    request = service.files().create(
      body=file_metadata,
      media_body=media,
      fields='id, name'
    )
    
    response = None
    last_progress = -1
    while response is None:
      status, response = request.next_chunk()
      if status:
        progress = int(status.progress() * 100)
        if progress != last_progress:
          if progress_callback:
            progress_callback(progress)
          last_progress = progress
    
    file_id = response.get('id')
    
    if status_callback:
      status_callback(f"File '{file_name}' uploaded successfully!")
    
    # Make file publicly accessible
    permission = {
      'type': 'anyone',
      'role': 'reader'
    }
    service.permissions().create(
      fileId=file_id,
      body=permission
    ).execute()
    
    # Get shareable link
    shareable_link = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
    
    # Generate QR code
    qr = qrcode.QRCode(
      version=1,
      error_correction=qrcode.constants.ERROR_CORRECT_L,
      box_size=10,
      border=4,
    )
    qr.add_data(shareable_link)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Save QR code with date/time format
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    qr_filename = f"QR_code_{timestamp}.png"
    qr_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), qr_filename)
    img.save(qr_path)
    
    if status_callback:
      status_callback(f"QR code saved as: {qr_filename}")
    
    return {'file_id': file_id, 'shareable_link': shareable_link, 'qr_path': qr_path, 'qr_filename': qr_filename}
  except HttpError as error:
    if status_callback:
      status_callback(f"An error occurred: {error}")
    return None


def get_google_drive_service():
  """Authenticate and return Google Drive service."""
  creds = None
  if os.path.exists("token.json"):
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
  if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
      creds.refresh(Request())
    else:
      flow = InstalledAppFlow.from_client_secrets_file(
          "credentials.json", SCOPES
      )
      creds = flow.run_local_server(port=0)
    with open("token.json", "w") as token:
      token.write(creds.to_json())
  
  return build("drive", "v3", credentials=creds)


class QRGeneratorApp(ctk.CTk):
  def __init__(self):
    super().__init__()
    
    # Configure window
    self.title("QR Code Generator")
    self.geometry("700x550")
    self.resizable(False, False)
    
    # Set theme
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    
    # Variables
    self.selected_file = None
    self.upload_window = None
    
    # Create main UI
    self.create_main_ui()
  
  def create_main_ui(self):
    """Create the main UI."""
    # Header
    header_frame = ctk.CTkFrame(self, fg_color="transparent")
    header_frame.pack(pady=30)
    
    title_label = ctk.CTkLabel(
      header_frame,
      text="Upload PDF to Generate QR Code",
      font=ctk.CTkFont(size=24, weight="bold")
    )
    title_label.pack()
    
    subtitle_label = ctk.CTkLabel(
      header_frame,
      text="Upload your PDF file and get a QR code",
      font=ctk.CTkFont(size=13),
      text_color="gray"
    )
    subtitle_label.pack(pady=(5, 0))
    
    # File selection area
    self.file_frame = ctk.CTkFrame(self, corner_radius=15)
    self.file_frame.pack(pady=20, padx=40, fill="x")
    
    # File display
    self.file_label = ctk.CTkLabel(
      self.file_frame,
      text="No file selected",
      font=ctk.CTkFont(size=14),
      text_color="gray"
    )
    self.file_label.pack(pady=20)
    
    # Browse button
    self.browse_btn = ctk.CTkButton(
      self,
      text="Browse File",
      font=ctk.CTkFont(size=15, weight="bold"),
      width=200,
      height=45,
      corner_radius=10,
      command=self.browse_file
    )
    self.browse_btn.pack(pady=10)
    
    # Upload button
    self.upload_btn = ctk.CTkButton(
      self,
      text="Upload and Generate QR",
      font=ctk.CTkFont(size=15, weight="bold"),
      width=250,
      height=50,
      corner_radius=10,
      fg_color="#00A8E8",
      hover_color="#0088c0",
      state="disabled",
      command=self.start_upload
    )
    self.upload_btn.pack(pady=10)
    
    # Status label
    self.status_label = ctk.CTkLabel(
      self,
      text="",
      font=ctk.CTkFont(size=12),
      text_color="gray"
    )
    self.status_label.pack(pady=10)
    
  def browse_file(self):
    """Open file dialog to select PDF."""
    file_path = filedialog.askopenfilename(
      title="Select PDF File",
      filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
    )
    
    if file_path:
      self.selected_file = file_path
      file_name = os.path.basename(file_path)
      self.file_label.configure(text=f"📄 {file_name}", text_color="#00A8E8")
      self.upload_btn.configure(state="normal")
      self.status_label.configure(text="")
  
  def start_upload(self):
    """Start the upload process in a separate thread."""
    if not self.selected_file:
      messagebox.showerror("Error", "Please select a file first!")
      return

    if not has_internet_connection():
      messagebox.showerror(
        "No Internet Connection",
        "You don't have an internet connection. Please enable Wi-Fi or Ethernet and try again."
      )
      return
    
    # Disable upload button
    self.upload_btn.configure(state="disabled")
    self.browse_btn.configure(state="disabled")
    
    # Create upload progress window
    self.show_upload_window()
    
    # Start upload in separate thread
    thread = threading.Thread(target=self.upload_process, daemon=True)
    thread.start()
  
  def show_upload_window(self):
    """Show the upload progress window."""
    self.upload_window = ctk.CTkToplevel(self)
    self.upload_window.title("Uploading")
    self.upload_window.geometry("500x300")
    self.upload_window.resizable(False, False)
    self.upload_window.transient(self)
    
    # Center the window
    self.upload_window.update_idletasks()
    x = (self.upload_window.winfo_screenwidth() // 2) - (500 // 2)
    y = (self.upload_window.winfo_screenheight() // 2) - (300 // 2)
    self.upload_window.geometry(f"500x300+{x}+{y}")
    self.upload_window.update_idletasks()
    self.upload_window.wait_visibility()
    self.upload_window.grab_set()
    
    # Prevent closing during upload
    self.upload_window.protocol("WM_DELETE_WINDOW", lambda: None)
    
    # Cloud icon area
    icon_frame = ctk.CTkFrame(self.upload_window, fg_color="transparent")
    icon_frame.pack(pady=30)
    
    # Cloud icon (using emoji)
    cloud_label = ctk.CTkLabel(
      icon_frame,
      text="☁️",
      font=ctk.CTkFont(size=50)
    )
    cloud_label.pack()
    
    # Progress percentage
    self.progress_label = ctk.CTkLabel(
      self.upload_window,
      text="0%",
      font=ctk.CTkFont(size=48, weight="bold"),
      text_color="#00A8E8"
    )
    self.progress_label.pack(pady=10)
    
    # Status text
    self.upload_status_label = ctk.CTkLabel(
      self.upload_window,
      text="Uploading and generating...",
      font=ctk.CTkFont(size=14)
    )
    self.upload_status_label.pack(pady=5)
    
    # Progress bar
    progress_frame = ctk.CTkFrame(self.upload_window, fg_color="transparent")
    progress_frame.pack(pady=20, padx=40, fill="x")
    
    # Start and Finish labels
    labels_frame = ctk.CTkFrame(progress_frame, fg_color="transparent")
    labels_frame.pack(fill="x")
    
    start_label = ctk.CTkLabel(
      labels_frame,
      text="START",
      font=ctk.CTkFont(size=10),
      text_color="gray"
    )
    start_label.pack(side="left")
    
    finish_label = ctk.CTkLabel(
      labels_frame,
      text="FINISH",
      font=ctk.CTkFont(size=10),
      text_color="gray"
    )
    finish_label.pack(side="right")
    
    # Progress bar
    self.progress_bar = ctk.CTkProgressBar(
      progress_frame,
      width=400,
      height=8,
      corner_radius=4,
      progress_color="#00A8E8"
    )
    self.progress_bar.pack(pady=5)
    self.progress_bar.set(0)
    
    # Warning text
    warning_label = ctk.CTkLabel(
      self.upload_window,
      text="Please do not close this window while we process your\nPDF.",
      font=ctk.CTkFont(size=11),
      text_color="gray"
    )
    warning_label.pack(pady=10)
    
    # Cancel button (disabled during upload)
    self.cancel_btn = ctk.CTkButton(
      self.upload_window,
      text="✕ Cancel Upload",
      font=ctk.CTkFont(size=12),
      fg_color="transparent",
      text_color="gray",
      hover_color="#f0f0f0",
      state="disabled"
    )
    self.cancel_btn.pack(pady=5)
  
  def update_progress(self, progress):
    """Update progress bar and percentage."""
    if self.upload_window and self.upload_window.winfo_exists():
      self.progress_bar.set(progress / 100)
      self.progress_label.configure(text=f"{progress}%")
  
  def update_status(self, message):
    """Update status message."""
    if self.upload_window and self.upload_window.winfo_exists():
      self.upload_status_label.configure(text=message)
  
  def upload_process(self):
    """Handle the upload process."""
    try:
      if not has_internet_connection():
        self.after(
          0,
          lambda: self.upload_error(
            "You don't have an internet connection. Please enable Wi-Fi or Ethernet and try again."
          )
        )
        return

      # Get Google Drive service
      service = get_google_drive_service()
      
      # Find or create folder
      folder_id = find_or_create_folder(service, "QR_generator")
      
      if not folder_id:
        self.after(0, lambda: self.upload_error("Failed to find or create folder"))
        return
      # Upload file
      result = upload_file_to_drive(
        service,
        self.selected_file,
        folder_id,
        progress_callback=lambda p: self.after(0, lambda: self.update_progress(p)),
        status_callback=lambda m: self.after(0, lambda: self.update_status(m))
      )
      if result:
        self.after(0, lambda: self.upload_complete(result))
      else:
        self.after(0, lambda: self.upload_error("Upload failed"))
        
    except Exception as e:
      self.after(0, lambda: self.upload_error(str(e)))
  
  def upload_complete(self, result):
    """Handle successful upload."""
    if self.upload_window and self.upload_window.winfo_exists():
      self.upload_window.destroy()
    
    # Show success window
    self.show_success_window(result)
    
    # Re-enable buttons
    self.upload_btn.configure(state="normal")
    self.browse_btn.configure(state="normal")
  
  def upload_error(self, error_message):
    """Handle upload error."""
    if self.upload_window and self.upload_window.winfo_exists():
      self.upload_window.destroy()
    
    messagebox.showerror("Upload Error", f"An error occurred:\n{error_message}")
    
    # Re-enable buttons
    self.upload_btn.configure(state="normal")
    self.browse_btn.configure(state="normal")
  
  def show_success_window(self, result):
    """Show success window with QR code."""
    success_window = ctk.CTkToplevel(self)
    success_window.title("Success!")
    success_window.geometry("600x650")
    success_window.resizable(False, False)
    
    # Center the window
    success_window.update_idletasks()
    x = (success_window.winfo_screenwidth() // 2) - (600 // 2)
    y = (success_window.winfo_screenheight() // 2) - (650 // 2)
    success_window.geometry(f"600x650+{x}+{y}")
    
    # Success icon
    success_label = ctk.CTkLabel(
      success_window,
      text="✓",
      font=ctk.CTkFont(size=60, weight="bold"),
      text_color="#00C851"
    )
    success_label.pack(pady=20)
    
    # Success message
    message_label = ctk.CTkLabel(
      success_window,
      text="Upload Complete!",
      font=ctk.CTkFont(size=24, weight="bold")
    )
    message_label.pack(pady=10)
    
    # QR Code display
    qr_frame = ctk.CTkFrame(success_window, corner_radius=15)
    qr_frame.pack(pady=20, padx=40)
    
    try:
      # Load and display QR code
      qr_image = Image.open(result['qr_path'])
      qr_image = qr_image.resize((250, 250), Image.Resampling.LANCZOS)
      qr_photo = ImageTk.PhotoImage(qr_image)
      
      qr_label = ctk.CTkLabel(qr_frame, image=qr_photo, text="")
      qr_label.image = qr_photo  # Keep a reference
      qr_label.pack(pady=20, padx=20)
    except Exception as e:
      error_label = ctk.CTkLabel(
        qr_frame,
        text=f"Could not load QR code\n{e}",
        text_color="red"
      )
      error_label.pack(pady=20)
    
    # File info
    info_label = ctk.CTkLabel(
      success_window,
      text=f"QR Code saved as: {result['qr_filename']}",
      font=ctk.CTkFont(size=12),
      text_color="gray"
    )
    info_label.pack(pady=5)
    
    # Link display
    link_frame = ctk.CTkFrame(success_window, corner_radius=10)
    link_frame.pack(pady=10, padx=40, fill="x")
    
    link_label = ctk.CTkLabel(
      link_frame,
      text=result['shareable_link'],
      font=ctk.CTkFont(size=10),
      text_color="#00A8E8"
    )
    link_label.pack(pady=10, padx=10)
    
    # Copy link button
    copy_btn = ctk.CTkButton(
      success_window,
      text="Copy Link",
      font=ctk.CTkFont(size=14),
      width=150,
      height=40,
      corner_radius=8,
      command=lambda: self.copy_to_clipboard(result['shareable_link'])
    )
    copy_btn.pack(pady=10)
    
    # Close button
    close_btn = ctk.CTkButton(
      success_window,
      text="Close",
      font=ctk.CTkFont(size=14),
      width=150,
      height=40,
      corner_radius=8,
      fg_color="gray",
      hover_color="#666666",
      command=success_window.destroy
    )
    close_btn.pack(pady=5)
  
  def copy_to_clipboard(self, text):
    """Copy text to clipboard."""
    self.clipboard_clear()
    self.clipboard_append(text)
    messagebox.showinfo("Copied", "Link copied to clipboard!")


def main():
  """Launch the GUI application."""
  app = QRGeneratorApp()
  app.mainloop()


if __name__ == "__main__":
  main()
