export interface VoiceInfo {
  name: string;
  has_transcript: boolean;
  format: string;
}

class VoiceService {
  private baseUrl: string;

  constructor() {
    // Determine backend URL
    const protocol = window.location.protocol;
    const host = window.location.hostname;
    const port = "8000"; // Shore-Assistant backend port
    this.baseUrl = `${protocol}//${host}:${port}/api/voices`;
  }

  async getVoices(): Promise<VoiceInfo[]> {
    const response = await fetch(this.baseUrl);
    if (!response.ok) throw new Error("Failed to fetch voices");
    return response.json();
  }

  async uploadVoice(name: string, transcript: string, audioFile: File): Promise<any> {
    const formData = new FormData();
    formData.append("name", name);
    formData.append("transcript", transcript);
    formData.append("audio", audioFile);

    const response = await fetch(this.baseUrl, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Failed to upload voice");
    }

    return response.json();
  }

  async deleteVoice(name: string): Promise<any> {
    const response = await fetch(`${this.baseUrl}/${name}`, {
      method: "DELETE",
    });

    if (!response.ok) throw new Error("Failed to delete voice");
    return response.json();
  }
}

export const voiceService = new VoiceService();
