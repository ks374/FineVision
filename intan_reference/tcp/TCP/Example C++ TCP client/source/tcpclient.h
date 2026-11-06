#ifndef TCPCLIENT_H
#define TCPCLIENT_H

#include <QtWidgets>

class QTcpSocket;
class QLineEdit;
class QSpinBox;
class QPushButton;
class QTextEdit;
class QLabel;

class TCPClient : public QWidget
{
    Q_OBJECT

public:
    TCPClient(QWidget *parent = 0);

private:
    QTcpSocket *commandSocket;
    QTcpSocket *waveformSocket;
    QTcpSocket *spikeSocket;
    QLabel *commandHostLabel;
    QLineEdit *commandHost;
    QLabel *waveformHostLabel;
    QLineEdit *waveformHost;
    QLabel *spikeHostLabel;
    QLineEdit *spikeHost;
    QLabel *commandPortLabel;
    QSpinBox *commandPort;
    QLabel *waveformPortLabel;
    QSpinBox *waveformPort;
    QLabel *spikePortLabel;
    QSpinBox *spikePort;

    QPushButton *commandConnectButton;
    QPushButton *commandDisconnectButton;
    QPushButton *waveformConnectButton;
    QPushButton *waveformDisconnectButton;
    QPushButton *spikeConnectButton;
    QPushButton *spikeDisconnectButton;

    QLabel *routineLabel;
    QPushButton *startRoutineButton;
    QLabel *messageLabel;
    QTextEdit *messages;
    QLabel *commandLabel;
    QTextEdit *commandsTextEdit;
    QPushButton *sendCommandButton;

    QLabel *timestampLabel;
    QLabel *timestampText;

    QLabel *waveformLabel;
    QLabel *waveformText;

    QLabel *spikeLabel;
    QLabel *spikeText;

    qint64 beginTime;
    qint64 endTime;

    QByteArray waveformInputBuffer;
    QByteArray spikeInputBuffer;

    int waveformBytesPerFrame;
    int waveformBytesPerBlock;
    int blocksPerRead;
    int waveformBytes10Blocks;

    int totalWaveformDataBlocksProcessed;

    int bytesPerSpikeChunk;

    int totalSpikesProcessed;

    void processWaveformChunk();
    void processSpikeChunk();

protected:
    bool eventFilter(QObject *obj, QEvent *event);

public slots:
    void connectCommandToHost();
    void connectWaveformToHost();
    void connectSpikeToHost();

    void disconnectCommandFromHost();
    void disconnectWaveformFromHost();
    void disconnectSpikeFromHost();

    void startRoutineSlot();

    void commandConnected();
    void commandDisconnected();

    void waveformConnected();
    void waveformDisconnected();

    void spikeConnected();
    void spikeDisconnected();

    void readCommandServer();
    void sendCommand();

    void readWaveform();

    void readSpike();
};

#endif // TCPCLIENT_H
