import React, { useState, useEffect } from "react";
import {
  Flex,
  Text,
  Button,
  Card,
  Grid,
  Box,
  Heading,
  TextField,
  TextArea,
  Dialog,
  Callout,
  Badge,
} from "@radix-ui/themes";
import { voiceService, type VoiceInfo } from "@Shore/services/voice.service";

export default function PageVoices() {
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form State
  const [newName, setNewName] = useState("");
  const [newTranscript, setNewTranscript] = useState("");
  const [newFile, setNewFile] = useState<File | null>(null);

  useEffect(() => {
    loadVoices();
  }, []);

  const loadVoices = async () => {
    try {
      setLoading(true);
      const data = await voiceService.getVoices();
      setVoices(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newFile || !newName || !newTranscript) return;

    try {
      setIsUploading(true);
      await voiceService.uploadVoice(newName, newTranscript, newFile);
      setNewName("");
      setNewTranscript("");
      setNewFile(null);
      await loadVoices();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsUploading(false);
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete voice reference "${name}"?`)) return;
    try {
      await voiceService.deleteVoice(name);
      await loadVoices();
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <Flex direction="column" gap="6" p="6" style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <Flex justify="between" align="center">
        <Box>
          <Heading size="8" mb="2">
            Voice Management
          </Heading>
          <Text color="gray" size="3">
            Upload and manage reference audio for Shorekeeper's voice cloning.
          </Text>
        </Box>

        <Dialog.Root>
          <Dialog.Trigger>
            <Button size="3" variant="solid" color="indigo">
              Add New Voice
            </Button>
          </Dialog.Trigger>

          <Dialog.Content style={{ maxWidth: 500 }}>
            <Dialog.Title>Upload Reference Voice</Dialog.Title>
            <Dialog.Description size="2" mb="4">
              Upload a clear audio sample (ogg/wav) and providing the exact text spoken.
            </Dialog.Description>

            <form onSubmit={handleUpload}>
              <Flex direction="column" gap="4">
                <Box>
                  <Text as="div" size="2" mb="1" weight="bold">
                    Speaker Name
                  </Text>
                  <TextField.Root
                    placeholder="e.g. Shorekeeper_Alt"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    required
                  />
                </Box>

                <Box>
                  <Text as="div" size="2" mb="1" weight="bold">
                    Audio File
                  </Text>
                  <input
                    type="file"
                    accept=".wav,.ogg,.mp3,.flac"
                    onChange={(e) => setNewFile(e.target.files?.[0] || null)}
                    required
                    style={{
                      width: "100%",
                      padding: "8px",
                      border: "1px dashed var(--gray-6)",
                      borderRadius: "var(--radius-2)",
                    }}
                  />
                </Box>

                <Box>
                  <Text as="div" size="2" mb="1" weight="bold">
                    Transcript
                  </Text>
                  <TextArea
                    placeholder="Type the exact words spoken in the audio..."
                    value={newTranscript}
                    onChange={(e) => setNewTranscript(e.target.value)}
                    required
                    rows={4}
                  />
                </Box>

                <Flex gap="3" mt="4" justify="end">
                  <Dialog.Close>
                    <Button variant="soft" color="gray">
                      Cancel
                    </Button>
                  </Dialog.Close>
                  <Dialog.Close>
                    <Button type="submit" loading={isUploading} disabled={!newFile || !newName || !newTranscript}>
                      Upload Voice
                    </Button>
                  </Dialog.Close>
                </Flex>
              </Flex>
            </form>
          </Dialog.Content>
        </Dialog.Root>
      </Flex>

      {error && (
        <Callout.Root color="red" variant="soft">
          <Callout.Text>{error}</Callout.Text>
        </Callout.Root>
      )}

      {loading ? (
        <Text>Loading voices...</Text>
      ) : (
        <Grid columns={{ initial: "1", sm: "2", md: "3" }} gap="4">
          {voices.map((voice) => (
            <Card key={voice.name} size="2">
              <Flex direction="column" gap="3">
                <Flex justify="between" align="start">
                  <Box>
                    <Text as="div" size="3" weight="bold" mb="1">
                      {voice.name}
                    </Text>
                    <Flex gap="2">
                      <Badge color="indigo" variant="soft">
                        {voice.format.toUpperCase()}
                      </Badge>
                      {voice.has_transcript ? (
                        <Badge color="green" variant="soft">
                          Transcript OK
                        </Badge>
                      ) : (
                        <Badge color="red" variant="soft">
                          No Transcript
                        </Badge>
                      )}
                    </Flex>
                  </Box>
                  <Button
                    variant="ghost"
                    color="red"
                    size="1"
                    onClick={() => handleDelete(voice.name)}
                  >
                    Delete
                  </Button>
                </Flex>
              </Flex>
            </Card>
          ))}
        </Grid>
      )}
    </Flex>
  );
}
