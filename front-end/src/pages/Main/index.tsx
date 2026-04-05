import { Flex, Text, Button, Card, Badge, Box, ScrollArea } from "@radix-ui/themes";
import { useVADAudio } from "../../hooks/useVADAudio";

function PageMain() {
  const {
    isLoaded,
    isRecording,
    isSpeaking,
    vadScore,
    statusMessage,
    eventLogs,
    startRecording,
    stopRecording
  } = useVADAudio();

  return (
    <Flex direction="column" gap="4" align="center" justify="center" style={{ minHeight: '100vh', padding: '2rem' }}>
      <Card size="4" style={{ width: '100%', maxWidth: '600px' }}>
        <Flex direction="column" gap="4">
          <Flex justify="between" align="center">
            <Text size="5" weight="bold">Kiểm thử VAD (Voice Activity Detection)</Text>
            <Badge color={isLoaded ? "green" : "orange"} variant="soft">
              {isLoaded ? "Model Sẵn sàng" : "Đang tải Model..."}
            </Badge>
          </Flex>

          <Text size="2" color="gray">{statusMessage}</Text>

          {/* VAD Live Indicators */}
          <Flex align="center" justify="between" p="3" style={{ background: 'var(--gray-3)', borderRadius: 'var(--radius-3)' }}>
            <Flex align="center" gap="3">
               <Box 
                  style={{ 
                    width: 16, 
                    height: 16, 
                    borderRadius: '50%', 
                    backgroundColor: isSpeaking ? 'var(--red-9)' : 'var(--gray-8)',
                    boxShadow: isSpeaking ? '0 0 10px var(--red-9)' : 'none',
                    transition: 'all 0.1s ease'
                  }} 
               />
               <Text weight="medium">{isSpeaking ? 'Đang nói...' : 'Im lặng'}</Text>
            </Flex>
            <Badge color="blue" variant="surface">
               Xác suất: {vadScore.toFixed(3)}
            </Badge>
          </Flex>

          {/* Controls */}
          <Flex gap="3" mt="2">
            {!isRecording ? (
              <Button 
                size="3" 
                color="indigo" 
                variant="solid" 
                onClick={startRecording} 
                disabled={!isLoaded}
                style={{ flex: 1, cursor: isLoaded ? 'pointer' : 'not-allowed' }}
              >
                Cấp quyền & Khởi động Mic
              </Button>
            ) : (
              <Button 
                size="3" 
                color="red" 
                variant="soft" 
                onClick={stopRecording}
                style={{ flex: 1, cursor: 'pointer' }}
              >
                Dừng thu âm
              </Button>
            )}
          </Flex>
          
          {/* Logs */}
          <Box mt="4">
            <Text weight="bold" size="3" mb="2">Mảnh âm thanh chuẩn bị gửi lên Sever (speech-ready)</Text>
            {eventLogs.length > 0 ? (
                <ScrollArea type="always" scrollbars="vertical" style={{ height: 200, paddingRight: '1rem' }}>
                  <Flex direction="column" gap="2">
                    {eventLogs.map((log) => (
                      <Card key={log.id} size="1">
                         <Flex justify="between" align="center" wrap="wrap" gap="2">
                           <Flex direction="column">
                             <Text size="2" color="gray">{log.timestamp.toLocaleTimeString()}</Text>
                             <Text size="2" weight="medium">Dài: {log.duration.toFixed(0)} ms</Text>
                           </Flex>
                           {log.audioUrl && (
                             <audio src={log.audioUrl} controls style={{ height: '32px', maxWidth: '100%' }} />
                           )}
                         </Flex>
                      </Card>
                    ))}
                  </Flex>
               </ScrollArea>
            ) : (
                <Flex align="center" justify="center" p="4" style={{ background: 'var(--gray-2)', borderRadius: 'var(--radius-3)' }}>
                    <Text size="2" color="gray">Chưa có mảnh audio nào. Hãy thử nói vào Mic...</Text>
                </Flex>
            )}
            
          </Box>

        </Flex>
      </Card>
    </Flex>
  );
}

export default PageMain;
