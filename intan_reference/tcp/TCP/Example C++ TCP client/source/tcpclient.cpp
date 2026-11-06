#include <QtGui>
#include <QtNetwork>

#include <thread>
#include <chrono>

#include "tcpclient.h"


TCPClient::TCPClient(QWidget *parent)
    : QWidget(parent)
{
    setWindowTitle("TCP Client");

    // TCP Socket for commands
    commandSocket = new QTcpSocket(this);
    connect(commandSocket, SIGNAL(connected()), this, SLOT(commandConnected()));
    connect(commandSocket, SIGNAL(disconnected()), this, SLOT(commandDisconnected()));
    connect(commandSocket, SIGNAL(readyRead()), this, SLOT(readCommandServer()));
    commandHost = new QLineEdit("127.0.0.1", this);
    commandHostLabel = new QLabel("Host: ");
    commandPort = new QSpinBox(this);
    commandPort->setRange(0,9999);
    commandPort->setValue(5000);
    commandPortLabel = new QLabel("Port: ");
    commandConnectButton = new QPushButton("Connect", this);
    connect(commandConnectButton, SIGNAL(clicked()), this, SLOT(connectCommandToHost()));
    commandDisconnectButton = new QPushButton("Disconnect", this);
    connect(commandDisconnectButton, SIGNAL(clicked()), this, SLOT(disconnectCommandFromHost()));

    // TCP Socket for waveform data
    waveformSocket = new QTcpSocket(this);
    connect(waveformSocket, SIGNAL(connected()), this,  SLOT(waveformConnected()));
    connect(waveformSocket, SIGNAL(disconnected()), this, SLOT(waveformDisconnected()));
    connect(waveformSocket, SIGNAL(readyRead()), this, SLOT(readWaveform()));
    waveformHost = new QLineEdit("127.0.0.1", this);
    waveformHostLabel = new QLabel("Host: ");
    waveformPortLabel = new QLabel("Port: ");
    waveformPort = new QSpinBox(this);
    waveformPort->setRange(0,9999);
    waveformPort->setValue(5001);
    waveformConnectButton = new QPushButton("Connect", this);
    connect(waveformConnectButton, SIGNAL(clicked()), this, SLOT(connectWaveformToHost()));
    waveformDisconnectButton = new QPushButton("Disconnect", this);
    connect(waveformDisconnectButton, SIGNAL(clicked()), this, SLOT(disconnectWaveformFromHost()));

    // TCP Socket for spike data
    spikeSocket = new QTcpSocket(this);
    connect(spikeSocket, SIGNAL(connected()), this, SLOT(spikeConnected()));
    connect(spikeSocket, SIGNAL(disconnected()), this, SLOT(spikeDisconnected()));
    connect(spikeSocket, SIGNAL(readyRead()), this, SLOT(readSpike()));
    spikeHost = new QLineEdit("127.0.0.1", this);
    spikeHostLabel = new QLabel("Host: ");
    spikePortLabel = new QLabel("Port: ");
    spikePort = new QSpinBox(this);
    spikePort->setRange(0,9999);
    spikePort->setValue(5002);
    spikeConnectButton = new QPushButton("Connect", this);
    connect(spikeConnectButton, SIGNAL(clicked()), this, SLOT(connectSpikeToHost()));
    spikeDisconnectButton = new QPushButton("Disconnect", this);
    connect(spikeDisconnectButton, SIGNAL(clicked()), this, SLOT(disconnectSpikeFromHost()));

    // Routine that automatically connects, enables channels, and runs
    routineLabel = new QLabel("Example routine automatically connects all 3 sockets, enables 16 channels Wide and Spike, and runs controller.");
    startRoutineButton = new QPushButton("Start Example Routine", this);
    connect(startRoutineButton, SIGNAL(clicked()), this, SLOT(startRoutineSlot()));

    // Panel that contains messages
    messageLabel = new QLabel("Messages:", this);
    messages = new QTextEdit(this);
    messages->setReadOnly(true);

    // Panel that contains commands
    commandLabel = new QLabel("Commands:", this);
    commandsTextEdit = new QTextEdit(this);
    commandsTextEdit->installEventFilter(this);

    // Labels for timestamp, waveform, and spike
    timestampLabel = new QLabel("Timestamp: ");
    timestampText = new QLabel;
    waveformLabel = new QLabel("Waveform data blocks received: ");
    waveformText = new QLabel;
    spikeLabel = new QLabel("Total spikes received: ");
    spikeText = new QLabel;

    // Button to send commands over TCP Command Socket
    sendCommandButton = new QPushButton("Send", this);
    connect(sendCommandButton, SIGNAL(clicked()), this, SLOT(sendCommand()));

    QVBoxLayout *mainLayout = new QVBoxLayout;

    QHBoxLayout *commandHostRow = new QHBoxLayout;
    commandHostRow->addWidget(commandHostLabel);
    commandHostRow->addWidget(commandHost);

    QHBoxLayout *commandPortRow = new QHBoxLayout;
    commandPortRow->addWidget(commandPortLabel);
    commandPortRow->addWidget(commandPort);

    QVBoxLayout *commandColumnLayout = new QVBoxLayout;
    commandColumnLayout->addLayout(commandHostRow);
    commandColumnLayout->addLayout(commandPortRow);
    commandColumnLayout->addWidget(commandConnectButton);
    commandColumnLayout->addWidget(commandDisconnectButton);

    QGroupBox *commandColumn = new QGroupBox;
    commandColumn->setLayout(commandColumnLayout);

    QHBoxLayout *waveformHostRow = new QHBoxLayout;
    waveformHostRow->addWidget(waveformHostLabel);
    waveformHostRow->addWidget(waveformHost);

    QHBoxLayout *waveformPortRow = new QHBoxLayout;
    waveformPortRow->addWidget(waveformPortLabel);
    waveformPortRow->addWidget(waveformPort);

    QVBoxLayout *waveformColumnLayout = new QVBoxLayout;
    waveformColumnLayout->addLayout(waveformHostRow);
    waveformColumnLayout->addLayout(waveformPortRow);
    waveformColumnLayout->addWidget(waveformConnectButton);
    waveformColumnLayout->addWidget(waveformDisconnectButton);

    QGroupBox *waveformColumn = new QGroupBox;
    waveformColumn->setLayout(waveformColumnLayout);

    QHBoxLayout *spikeHostRow = new QHBoxLayout;
    spikeHostRow->addWidget(spikeHostLabel);
    spikeHostRow->addWidget(spikeHost);

    QHBoxLayout *spikePortRow = new QHBoxLayout;
    spikePortRow->addWidget(spikePortLabel);
    spikePortRow->addWidget(spikePort);

    QVBoxLayout *spikeColumnLayout = new QVBoxLayout;
    spikeColumnLayout->addLayout(spikeHostRow);
    spikeColumnLayout->addLayout(spikePortRow);
    spikeColumnLayout->addWidget(spikeConnectButton);
    spikeColumnLayout->addWidget(spikeDisconnectButton);

    QGroupBox *spikeColumn = new QGroupBox;
    spikeColumn->setLayout(spikeColumnLayout);

    QHBoxLayout *socketsRow = new QHBoxLayout;
    socketsRow->addWidget(commandColumn);
    socketsRow->addWidget(waveformColumn);
    socketsRow->addWidget(spikeColumn);

    QHBoxLayout *timestampRow = new QHBoxLayout;
    timestampRow->addWidget(timestampLabel);
    timestampRow->addWidget(timestampText);

    QHBoxLayout *waveformRow = new QHBoxLayout;
    waveformRow->addWidget(waveformLabel);
    waveformRow->addWidget(waveformText);

    QHBoxLayout *spikeRow = new QHBoxLayout;
    spikeRow->addWidget(spikeLabel);
    spikeRow->addWidget(spikeText);

    mainLayout->addLayout(socketsRow);

    mainLayout->addWidget(routineLabel);
    mainLayout->addWidget(startRoutineButton);
    mainLayout->addWidget(messageLabel);
    mainLayout->addWidget(messages);
    mainLayout->addWidget(commandLabel);
    mainLayout->addWidget(commandsTextEdit);
    mainLayout->addLayout(timestampRow);
    mainLayout->addLayout(waveformRow);
    mainLayout->addLayout(spikeRow);
    mainLayout->addWidget(sendCommandButton);

    setLayout(mainLayout);

    // Create waveformInputBuffer as a QByteArray to contain waveform data.
    waveformBytesPerFrame = 4 + 2 * 16;
    waveformBytesPerBlock = 128 * waveformBytesPerFrame + 4;
    blocksPerRead = 10;
    waveformBytes10Blocks = blocksPerRead * waveformBytesPerBlock;
    waveformInputBuffer.resize(waveformBytes10Blocks);
    totalWaveformDataBlocksProcessed = 0;

    // Each spike chunk contains 4 bytes for magic number, 5 bytes for native channel name, 4 bytes for timestamp, and 1 byte for id. Total: 14 bytes.
    totalSpikesProcessed = 0;
    bytesPerSpikeChunk = 14;
}

bool TCPClient::eventFilter(QObject *obj, QEvent *event)
{
    // When user presses enter, send command.
    if (obj == commandsTextEdit) {
        if (event->type() == QEvent::KeyPress) {
            QKeyEvent *keyEvent = static_cast<QKeyEvent*>(event);
            if (keyEvent->key() == Qt::Key_Return) {
                sendCommand();
                return true;
            }
        }
    }
    return false;
}

// Connect TCP Command Socket to the currently specified host address/port
void TCPClient::connectCommandToHost()
{
    commandSocket->connectToHost(QHostAddress(commandHost->text()), commandPort->value());
}

// Connect TCP Waveform Data Socket to the currently specified host address/port
void TCPClient::connectWaveformToHost()
{
    waveformSocket->connectToHost(QHostAddress(waveformHost->text()), waveformPort->value());
}

// Connect TCP Spike Data Socket to the currently specified host address/port
void TCPClient::connectSpikeToHost()
{
    spikeSocket->connectToHost(QHostAddress(spikeHost->text()), spikePort->value());
}

// Disconnect TCP Command Socket from the currently connected host address/port
void TCPClient::disconnectCommandFromHost()
{
    commandSocket->disconnectFromHost();
}

// Disconnect TCP Waveform Data Socket from the currently connected host address/port
void TCPClient::disconnectWaveformFromHost()
{
    waveformSocket->disconnectFromHost();
}

// Disconnect TCP Spike Data Socket from the currently connect host address/port
void TCPClient::disconnectSpikeFromHost()
{
    spikeSocket->disconnectFromHost();
}

// Run the routine that connects to the command, waveform, and spike servers, enables TCP data output on some channels, and starts the controller running
void TCPClient::startRoutineSlot()
{
    // Connect to TCP command server
    connectCommandToHost();

    // Connect to TCP waveform server
    connectWaveformToHost();

    // Connect to TCP spike server
    connectSpikeToHost();

    // Wait for all 3 connections to be made
    while (commandSocket->state() != QAbstractSocket::ConnectedState ||
           waveformSocket->state() != QAbstractSocket::ConnectedState ||
           spikeSocket->state() != QAbstractSocket::ConnectedState) {
        qApp->processEvents();
    }

    // Clear TCP data output to ensure no TCP channels are enabled at the beginning of this routine
    commandSocket->write("execute clearalldataoutputs;");
    commandSocket->waitForBytesWritten();

    // Enable wide and spike output for first 16 channels
    commandSocket->write("set a-000.tcpdataoutputenabled true; set a-000.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-001.tcpdataoutputenabled true; set a-001.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-002.tcpdataoutputenabled true; set a-002.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-003.tcpdataoutputenabled true; set a-003.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-004.tcpdataoutputenabled true; set a-004.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-005.tcpdataoutputenabled true; set a-005.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-006.tcpdataoutputenabled true; set a-006.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-007.tcpdataoutputenabled true; set a-007.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-008.tcpdataoutputenabled true; set a-008.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-009.tcpdataoutputenabled true; set a-009.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-010.tcpdataoutputenabled true; set a-010.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-011.tcpdataoutputenabled true; set a-011.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-012.tcpdataoutputenabled true; set a-012.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-013.tcpdataoutputenabled true; set a-013.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-014.tcpdataoutputenabled true; set a-014.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set a-015.tcpdataoutputenabled true; set a-015.tcpdataoutputenabledspike true;");
    commandSocket->waitForBytesWritten();

    commandSocket->write("set runmode run;");
    commandSocket->waitForBytesWritten();

    beginTime = QDateTime::currentMSecsSinceEpoch();
}

// Executes when TCP Command Socket is successfully connected
void TCPClient::commandConnected()
{
    messages->append("Command Port Connected");
}

// Executes when TCP Command Socket is disconnected
void TCPClient::commandDisconnected()
{
    messages->append("Command Port Disconnected");
}

// Executes when text is received over TCP Command Socket
void TCPClient::readCommandServer()
{
    QString result;
    result = commandSocket->readAll();
    messages->append(result);
    return;
}

// Sends text over TCP Command Socket
void TCPClient::sendCommand()
{
    if (commandSocket->state() == commandSocket->ConnectedState) {
        commandSocket->write(commandsTextEdit->toPlainText().toLatin1());
        commandSocket->waitForBytesWritten();
    }
}

// Executes when TCP Waveform Data Socket is successfully connected
void TCPClient::waveformConnected()
{
    messages->append("Waveform Port Connected");
}

// Executes when TCP Waveform Data Socket is disconnected
void TCPClient::waveformDisconnected()
{
    messages->append("Waveform Port Disconnected");
}


// Read waveform data in 10-block chunks when it comes in on TCP Waveform Data Sockets
void TCPClient::readWaveform()
{
    if (waveformSocket->bytesAvailable() > waveformBytes10Blocks) {
        processWaveformChunk();
    }

    return;
}

// Process 10-data-block chunk of waveform data.
// This processing it minimal; just checks magic numbers, parses timestamp, and counts how many data blocks have been processed.
// If more sophisticated processing of incoming waveform data is desired, this function should be expanded.
void TCPClient::processWaveformChunk()
{
    waveformInputBuffer = waveformSocket->read(waveformBytes10Blocks);
    int i = 0;

    for (int block = 0; block < blocksPerRead; ++block) {
        uint32_t magicNum = ((uint8_t) waveformInputBuffer[i + 3] << 24) + ((uint8_t) waveformInputBuffer[i + 2] << 16) + ((uint8_t) waveformInputBuffer[i + 1] << 8) + (uint8_t) waveformInputBuffer[i];
        if (magicNum != 0x2ef07a08) {
            qDebug() << "ERROR READING WAVEFORM MAGIC NUMBER... read magicNum: " << magicNum << " block: " << block;
        }
        i += 4;
        for (int frame = 0; frame < 128; ++frame) {
            int32_t timestamp = (int32_t)((uint8_t) waveformInputBuffer[i + 3] << 24) + ((uint8_t) waveformInputBuffer[i + 2] << 16) + ((uint8_t) waveformInputBuffer[i + 1] << 8) + (uint8_t) waveformInputBuffer[i];
            i += 4;
            if (frame == 0 && block == 0) {
                timestampText->setText(QString::number(timestamp));
            }
            for (int channel = 0; channel < 16; ++channel) {
                uint16_t dataSample = (uint16_t)((uint8_t) waveformInputBuffer[i + 1] << 8) + (uint8_t) waveformInputBuffer[i];
                i += 2;
            }
        }
    }
    totalWaveformDataBlocksProcessed += 10;
    waveformText->setText(QString::number(totalWaveformDataBlocksProcessed));
}

// Executes when TCP Spike Data Socket is successfully connected
void TCPClient::spikeConnected()
{
    messages->append("Spike Port Connected");
}

// Executes when TCP Spike Data Socket is disconnected
void TCPClient::spikeDisconnected()
{
    messages->append("Spike Port Disconnected");
}

// Read spike data when it comes in on TCP Waveform Data Sockets
void TCPClient::readSpike()
{
    spikeInputBuffer.append(spikeSocket->readAll());
    processSpikeChunk();
    spikeInputBuffer.clear();

    return;
}

// Process chunk of spike data.
// This processing is minimal; just checks magic number and counts how many spikes have been processed.
// If more sophisticated processing of incoming spike data is desired, this function should be expanded.
void TCPClient::processSpikeChunk()
{
    int i = 0;
    int chunksToRead = spikeInputBuffer.size() / bytesPerSpikeChunk;

    for (int chunk = 0; chunk < chunksToRead; ++chunk) {
        uint32_t magicNum = ((uint8_t) spikeInputBuffer[i + 3] << 24) + ((uint8_t) spikeInputBuffer[i + 2] << 16) + ((uint8_t) spikeInputBuffer[i + 1] << 8) + (uint8_t) spikeInputBuffer[i];
        if (magicNum != 0x3ae2710f) {
            qDebug( )<< "ERROR READING SPIKE MAGIC NUMBER... read magicNum: " << magicNum << " chunk: " << chunk;
        }
        i += 4;
        // Skip 5 bytes for chars of native channel name, 4 bytes of uint32 timesetamp, 1 byte of uint8 id (10)
        i += 10;
        totalSpikesProcessed++;
    }
    spikeText->setText(QString::number(totalSpikesProcessed));
}
