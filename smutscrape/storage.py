#!/usr/bin/env python3
"""
Storage Management Module for Smutscrape

This module provides centralized file storage operations including
SMB uploads, local file management, permissions, and progress tracking.
"""

import os
import pwd
import grp
import shutil
import tempfile
from typing import Dict, Any, Optional
from loguru import logger
from tqdm import tqdm
from smb.SMBConnection import SMBConnection


class ProgressFile:
    """A file-like wrapper to track progress during SMB upload."""
    
    def __init__(self, file_obj, progress_bar):
        """Initialize progress file wrapper.
        
        Args:
            file_obj: File object to wrap
            progress_bar: tqdm progress bar to update
        """
        self.file_obj = file_obj
        self.pbar = progress_bar
        self.total_size = os.fstat(file_obj.fileno()).st_size
    
    def read(self, size=-1):
        """Read data and update progress bar."""
        data = self.file_obj.read(size)
        if data:
            self.pbar.update(len(data))
        return data
    
    def __getattr__(self, name):
        """Delegate attribute access to wrapped file object."""
        return getattr(self.file_obj, name)


class StorageManager:
    """Manages all file storage operations including SMB and local storage."""
    
    def __init__(self):
        """Initialize the storage manager."""
        pass
    
    def apply_permissions(self, file_path: str, destination_config: Dict[str, Any]) -> bool:
        """Apply file permissions based on destination configuration.
        
        Args:
            file_path: Path to the file
            destination_config: Configuration dict containing permissions settings
            
        Returns:
            True if successful, False otherwise
        """
        if 'permissions' not in destination_config:
            return True
            
        permissions = destination_config['permissions']
        try:
            # Handle owner/uid
            if 'owner' in permissions and permissions['owner'].isalpha():
                uid = pwd.getpwnam(permissions['owner']).pw_uid
            else:
                uid = int(permissions.get('uid', -1))
            
            # Handle group/gid
            if 'group' in permissions and permissions['group'].isalpha():
                gid = grp.getgrnam(permissions['group']).gr_gid
            else:
                gid = int(permissions.get('gid', -1))
            
            # Apply ownership if specified
            if uid != -1 or gid != -1:
                current_uid = os.stat(file_path).st_uid if uid == -1 else uid
                current_gid = os.stat(file_path).st_gid if gid == -1 else gid
                os.chown(file_path, current_uid, current_gid)
                logger.debug(f"Applied ownership {current_uid}:{current_gid} to {file_path}")
            
            # Apply file mode if specified
            if 'mode' in permissions:
                os.chmod(file_path, int(permissions['mode'], 8))
                logger.debug(f"Applied mode {permissions['mode']} to {file_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to apply permissions to {file_path}: {e}")
            return False
    
    def file_exists_on_smb(self, destination_config: Dict[str, Any], path: str) -> bool:
        """Check if a file exists on SMB share.
        
        Args:
            destination_config: SMB configuration
            path: Remote path to check
            
        Returns:
            True if file exists, False otherwise
        """
        conn = SMBConnection(
            destination_config['username'], 
            destination_config['password'], 
            "videoscraper", 
            destination_config['server']
        )
        
        try:
            if not conn.connect(destination_config['server'], 445):
                raise ConnectionError(f"Failed to connect to SMB server {destination_config['server']}")
            
            logger.debug(f"Connected to SMB server, checking {path}")
            try:
                conn.getAttributes(destination_config['share'], path)
                return True
            except:
                return False
                
        except Exception as e:
            logger.debug(f"Error checking SMB file existence for {path}: {e}")
            return False
        finally:
            try:
                conn.close()
            except:
                pass
    
    def upload_to_smb(self, local_path: str, smb_path: str, destination_config: Dict[str, Any], 
                      overwrite: bool = False) -> bool:
        """Upload a file to SMB share with progress tracking.
        
        Args:
            local_path: Local file path
            smb_path: Remote SMB path
            destination_config: SMB configuration
            overwrite: Whether to overwrite existing files
            
        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"Connecting to SMB for {os.path.basename(local_path)} -> {smb_path}")
        
        conn = SMBConnection(
            destination_config['username'], 
            destination_config['password'], 
            "videoscraper", 
            destination_config['server']
        )
        
        connected = False
        try:
            connected = conn.connect(destination_config['server'], 445)
            if not connected:
                logger.error(f"Failed to connect to SMB share for {smb_path}")
                return False
            
            # Check if file exists and respect overwrite flag
            if not overwrite and self.file_exists_on_smb(destination_config, smb_path):
                logger.info(f"File '{os.path.basename(smb_path)}' exists on SMB share '{destination_config['share']}' at '{smb_path}'. Skipping upload.")
                return True
            
            # Upload with progress tracking
            file_size = os.path.getsize(local_path)
            with open(local_path, 'rb') as file:
                with tqdm(total=file_size, unit='B', unit_scale=True, 
                         desc=f"Uploading {os.path.basename(local_path)} to SMB") as pbar:
                    progress_file = ProgressFile(file, pbar)
                    conn.storeFile(destination_config['share'], smb_path, progress_file)
            
            logger.debug(f"Successfully stored file on SMB: {smb_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error during SMB operation for {os.path.basename(local_path)} to {smb_path}: {e}")
            return False
        finally:
            if connected and hasattr(conn, 'sock') and conn.sock:
                try:
                    conn.close()
                    logger.debug(f"SMB connection closed for {smb_path}")
                except:
                    pass
    
    def manage_file(self, destination_path: str, destination_config: Dict[str, Any], 
                    overwrite: bool = False, video_url: Optional[str] = None, 
                    state_set: Optional[set] = None) -> bool:
        """Move or upload the video (and NFO) to the final destination.
        
        Args:
            destination_path: Local file path to manage
            destination_config: Destination configuration
            overwrite: Whether to overwrite existing files
            video_url: Optional video URL for logging
            state_set: Optional state set for tracking
            
        Returns:
            True if successful, False otherwise
        """
        if destination_config['type'] == 'smb':
            return self._manage_smb_file(destination_path, destination_config, overwrite)
        else:
            return self._manage_local_file(destination_path, destination_config, overwrite)
    
    def _manage_smb_file(self, destination_path: str, destination_config: Dict[str, Any], 
                        overwrite: bool = False) -> bool:
        """Handle SMB file management."""
        smb_path = os.path.join(destination_config['path'], os.path.basename(destination_path))
        smb_nfo_path = os.path.join(destination_config['path'], 
                                   f"{os.path.basename(destination_path).rsplit('.', 1)[0]}.nfo")
        
        # Upload main video file
        smb_upload_successful = self.upload_to_smb(destination_path, smb_path, destination_config, overwrite)
        
        if smb_upload_successful:
            logger.success(f"Successfully processed video for SMB: {smb_path}")
            os.remove(destination_path)
            logger.debug(f"Removed temporary video file: {destination_path}")
            
            # Handle NFO file upload if it exists
            temp_nfo_path = f"{destination_path.rsplit('.', 1)[0]}.nfo"
            if os.path.exists(temp_nfo_path):
                nfo_upload_successful = self.upload_to_smb(temp_nfo_path, smb_nfo_path, 
                                                          destination_config, overwrite)
                if nfo_upload_successful:
                    os.remove(temp_nfo_path)
                    logger.debug(f"Removed temporary NFO file: {temp_nfo_path}")
                else:
                    logger.error(f"Failed to upload NFO file {os.path.basename(temp_nfo_path)} to SMB. It remains at {temp_nfo_path}")
            else:
                logger.debug(f"No NFO file found at {temp_nfo_path} to upload.")
        else:
            logger.error(f"Failed to upload video {os.path.basename(destination_path)} to SMB. It remains at {destination_path}")
            # Check for NFO file that wasn't uploaded due to video failure
            temp_nfo_path_on_failure = f"{destination_path.rsplit('.', 1)[0]}.nfo"
            if os.path.exists(temp_nfo_path_on_failure):
                logger.warning(f"NFO file {os.path.basename(temp_nfo_path_on_failure)} was not uploaded due to video upload failure. It remains at {temp_nfo_path_on_failure}")
        
        return smb_upload_successful
    
    def _manage_local_file(self, destination_path: str, destination_config: Dict[str, Any], 
                          overwrite: bool = False) -> bool:
        """Handle local file management."""
        final_path = os.path.join(destination_config['path'], os.path.basename(destination_path))
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        
        if not overwrite and os.path.exists(final_path):
            logger.info(f"File exists locally at {final_path}. Skipping move.")
            # Clean up temporary file if it's different from final
            if destination_path != final_path and os.path.exists(destination_path):
                os.remove(destination_path)
                logger.debug(f"Removed original file at {destination_path} as final already exists.")
            return True
        
        try:
            # Move main video file
            shutil.move(destination_path, final_path)
            self.apply_permissions(final_path, destination_config)
            logger.success(f"Moved to local destination: {final_path}")
            
            # Handle NFO file for local move
            temp_nfo_path = f"{destination_path.rsplit('.', 1)[0]}.nfo"
            final_nfo_path = f"{final_path.rsplit('.', 1)[0]}.nfo"
            
            if os.path.exists(temp_nfo_path):
                if not overwrite and os.path.exists(final_nfo_path):
                    logger.info(f"NFO file exists locally at {final_nfo_path}. Skipping move.")
                    if temp_nfo_path != final_nfo_path and os.path.exists(temp_nfo_path):
                        os.remove(temp_nfo_path)
                else:
                    shutil.move(temp_nfo_path, final_nfo_path)
                    self.apply_permissions(final_nfo_path, destination_config)
                    logger.debug(f"Moved NFO to {final_nfo_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to move {destination_path} to {final_path}: {e}")
            return False


# Global storage manager instance
storage_manager = None

def get_storage_manager():
    """Get or create the storage manager instance."""
    global storage_manager
    if storage_manager is None:
        storage_manager = StorageManager()
    return storage_manager 